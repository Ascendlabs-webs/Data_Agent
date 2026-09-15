"""
Explanation + audit tools: statistical summaries, query audits,
distribution analysis (skew/kurtosis, outliers, correlation).

The LLM provides the conversational explanation; these tools give the
model (and the user) quantitative context plus an audit trail:
confidence scoring, tables/columns used and alternatives.
"""
import math
import re
from collections import Counter


def _numeric_columns(data):
    """Return the names of columns that look numeric."""
    numeric = set()
    for row in data:
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric.add(key)
        if len(numeric) == len(row):
            break
    return sorted(numeric)


def _mean(values):
    return sum(values) / len(values) if values else 0


def _skew_kurt(values):
    """Skewness + excess kurtosis (pure python, no scipy needed)."""
    n = len(values)
    if n < 3:
        return 0.0, -3.0
    m = _mean(values)
    var = sum((v - m) ** 2 for v in values) / n
    if var == 0:
        return 0.0, -3.0
    std = math.sqrt(var)
    m3 = sum((v - m) ** 3 for v in values) / n
    m4 = sum((v - m) ** 4 for v in values) / n
    return round(m3 / (std ** 3), 2), round(m4 / (std ** 4) - 3, 2)


def _quartiles(sorted_vals):
    n = len(sorted_vals)
    if n == 0:
        return 0, 0
    mid = n // 2
    lower = sorted_vals[:mid]
    upper = sorted_vals[mid + 1:] if n % 2 else sorted_vals[mid:]
    def med(xs):
        if not xs:
            return sorted_vals[mid]
        m = len(xs) // 2
        return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2
    return med(lower), med(upper)


def _pearson(xs, ys):
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    xs, ys = xs[:n], ys[:n]
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return round(num / den, 2) if den else 0.0


def explain_data(data, top_n=5):
    """
    Build a statistical explanation of query results: row counts,
    min/max/avg/sum plus skew/kurtosis, IQR outliers and a
    Pearson correlation matrix for numeric columns.

    Args:
        data: list of dictionaries (query results).
        top_n: how many top values to list for categorical columns.

    Returns:
        Dictionary with row counts, column stats, outliers,
        correlation and a ready-made natural-language summary.
    """
    if not data:
        return {
            "success": False,
            "explanation": "No data was found.",
        }

    try:
        rows = list(data)
        columns = list(rows[0].keys())
        numeric = _numeric_columns(rows)

        info = {
            "row_count": len(rows),
            "columns": columns,
            "numeric_columns": numeric,
            "stats": {},
            "outliers": {},
            "explanation": "",
        }

        for column in numeric:
            values = [row[column] for row in rows
                      if isinstance(row.get(column), (int, float))
                      and not isinstance(row.get(column), bool)]
            if not values:
                continue
            skew, kurt = _skew_kurt(values)
            info["stats"][column] = {
                "min": min(values),
                "max": max(values),
                "avg": round(sum(values) / len(values), 2),
                "sum": round(sum(values), 2),
                "skew": skew,
                "kurtosis": kurt,
            }
            # IQR outliers
            s = sorted(values)
            q1, q3 = _quartiles(s)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outs = [v for v in values if v < lo or v > hi]
            if outs:
                info["outliers"][column] = {
                    "count": len(outs),
                    "lower": round(lo, 2),
                    "upper": round(hi, 2),
                    "sample": outs[:5],
                }

        # Correlation matrix (numeric pairs)
        if len(numeric) >= 2:
            cols = numeric[:8]  # cap for payload size
            series = {
                c: [r[c] for r in rows
                    if isinstance(r.get(c), (int, float))
                    and not isinstance(r.get(c), bool)]
                for c in cols
            }
            info["correlation"] = {
                "columns": cols,
                "matrix": [[_pearson(series[a], series[b]) for b in cols]
                           for a in cols],
            }

        categorical = [c for c in columns if c not in numeric]
        if categorical:
            column = categorical[0]
            counts = Counter(
                str(row[column]) for row in rows if row.get(column) is not None
            )
            info["top_values"] = {
                column: counts.most_common(top_n)
            }

        parts = [
            f"The query returned {len(rows)} record(s)"
            f" with fields: {', '.join(columns)}."
        ]
        for column, stats in info["stats"].items():
            parts.append(
                f"'{column}' ranges from {stats['min']} to {stats['max']}"
                f" (average {stats['avg']}, total {stats['sum']},"
                f" skew {stats['skew']}, kurtosis {stats['kurtosis']})."
            )
        for column, out in info.get("outliers", {}).items():
            parts.append(
                f"'{column}' has {out['count']} outlier(s)"
                f" outside [{out['lower']}, {out['upper']}]."
            )
        if "top_values" in info:
            for column, common in info["top_values"].items():
                listing = ", ".join(
                    f"{value} ({count})" for value, count in common[:3]
                )
                parts.append(
                    f"Most common values of '{column}': {listing}."
                )

        info["explanation"] = " ".join(parts)
        info["success"] = True
        return info

    except Exception as error:  # noqa: BLE001
        return {"success": False, "error": str(error)}


_TABLE_RE = re.compile(r"\b(?:from|join)\s+\"?([\w]+)\"?", re.IGNORECASE)


def assess_query(sql, db="grocery"):
    """
    Audit a SQL SELECT: tables/columns used, schema validation,
    confidence score (0-10), visualization recommendation and
    alternative query suggestions.

    Args:
        sql: SQL SELECT statement to audit.
        db: database name.

    Returns:
        Dictionary with confidence, tables_used, columns_used,
        issues, visualization_recommendation and alternatives.
    """
    try:
        from backend.database_tools import get_schema
        schema = get_schema(db)
    except Exception as error:  # noqa: BLE001
        return {"success": False, "error": str(error)}

    tables_used = list(dict.fromkeys(_TABLE_RE.findall(sql or "")))
    # crude column grab: identifiers in SELECT clause
    columns_used = []
    try:
        select_part = re.split(r"\bfrom\b", sql, flags=re.IGNORECASE)[0]
        select_part = re.sub(r"(?i)^\s*select\s+(distinct\s+)?", "", select_part)
        for token in re.split(r",", select_part):
            token = token.strip().strip('"').strip("'")
            token = re.split(r"\s+(as\s+)?", token, flags=re.IGNORECASE)[0]
            token = token.split(".")[-1].strip(' "()')
            if token and token != "*" and re.match(r"^[\w]+$", token):
                columns_used.append(token)
        columns_used = list(dict.fromkeys(columns_used))[:20]
    except Exception:  # noqa: BLE001
        columns_used = []

    issues = []
    confidence = 10.0
    known_tables = set(schema.keys())
    for table in tables_used:
        if table not in known_tables:
            issues.append(f"Unknown table '{table}'.")
            confidence -= 3
    if tables_used:
        known_cols = set()
        for table in tables_used:
            if table in schema:
                known_cols.update(c["name"] for c in schema[table].get("columns", []))
        for col in columns_used:
            if col.lower() in ("count", "sum", "avg", "min", "max"):
                continue
            if known_cols and col not in known_cols:
                issues.append(f"Column '{col}' not found in {tables_used}.")
                confidence -= 2
    else:
        issues.append("No tables detected in query.")
        confidence -= 4
    if re.search(r"(?i)select\s+\*", sql or ""):
        issues.append("SELECT * returns all columns; prefer explicit columns.")
        confidence -= 1
    if not re.search(r"(?i)\blimit\b", sql or ""):
        issues.append("No LIMIT clause; large tables may be slow.")
        confidence -= 0.5
    confidence = max(0.0, min(10.0, round(confidence, 1)))

    # Visualization recommendation
    viz = "Table"
    try:
        sample_cols = columns_used or []
        if len(sample_cols) >= 2:
            viz = "Bar Chart"
        if any(re.search(r"date|month|year|time", c, re.IGNORECASE) for c in sample_cols):
            viz = "Line Chart"
    except Exception:  # noqa: BLE001
        pass

    alternatives = []
    base = (sql or "").strip().rstrip(";")
    if base:
        if not re.search(r"(?i)\blimit\b", base):
            alternatives.append(base + " LIMIT 50")
        alternatives.append(
            re.sub(r"(?i)\blimit\s+\d+", "LIMIT 10", base)
            if re.search(r"(?i)\blimit\b", base) else base + " LIMIT 10"
        )
    alternatives = list(dict.fromkeys(a for a in alternatives if a != base))[:2]

    return {
        "success": True,
        "confidence": confidence,
        "tables_used": tables_used,
        "columns_used": columns_used,
        "issues": issues,
        "visualization_recommendation": viz,
        "alternatives": alternatives,
    }


if __name__ == "__main__":
    print(explain_data([
        {"city": "London", "revenue": 100},
        {"city": "Paris", "revenue": 200},
    ]))
