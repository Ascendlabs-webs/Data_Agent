"""
Database tools: schema discovery, SQL execution, chart generation.

These are the tools the LLM agent uses to interact with SQLite
databases. Every function returns plain JSON-serialisable data so
results can be streamed to the frontend and fed back to the model.
"""
import os
import re
import sqlite3
import time

from backend.config import DATABASES, MAX_QUERY_ROWS

# ------------------------------------------------------------------
# Output folders for generated charts / diagrams
# ------------------------------------------------------------------

CHART_FOLDER = os.path.join(os.path.dirname(__file__), "charts")
try:
    os.makedirs(CHART_FOLDER, exist_ok=True)
except OSError:
    CHART_FOLDER = os.path.join(os.path.dirname(__file__), "..", "..", "tmp", "charts")

# Vivid per-category palette (same hues as the frontend analytics
# dashboard): one distinct color per bar / pie slice, MITRA-style.
CHART_COLORS = [
    "#8B5CF6", "#06B6D4", "#10B981", "#F59E0B",
    "#F43F5E", "#EC4899", "#14B8A6", "#3B82F6",
]


def _is_postgres(db):
    info = DATABASES.get(db, {})
    return bool(info.get("url"))


def _connect(db):
    """Open a read-only connection (SQLite file or Postgres URL)."""
    if db not in DATABASES:
        raise ValueError(
            f"Unknown database '{db}'. Available: {', '.join(DATABASES)}"
        )
    info = DATABASES[db]
    if info.get("url"):
        import psycopg2  # lazy: only needed for Postgres
        import psycopg2.extras
        connection = psycopg2.connect(info["url"], connect_timeout=10)
        return connection
    path = info["path"]
    # Read-only URI: even if the SQL guard is bypassed, writes fail.
    connection = sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=10, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


def _close(connection, db):
    try:
        if _is_postgres(db):
            connection.close()
        else:
            connection.close()
    except Exception:  # noqa: BLE001
        pass


_FORBIDDEN = re.compile(
    r"(;|--|\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|transaction|commit|rollback)\b|/\*)",
    re.IGNORECASE,
)


def _jsonable(value):
    """Convert values (bytes etc.) into JSON-safe objects."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


# ==================================================================
# TOOL 1 - GET SCHEMA
# ==================================================================

def get_schema(db="grocery"):
    """
    Retrieve the complete schema of a database: tables, columns,
    primary keys, foreign keys, indexes, sample rows and row counts.
    Works for SQLite files and Postgres URLs.

    Args:
        db: database name (default 'grocery').

    Returns:
        Dictionary keyed by table name.
    """
    if _is_postgres(db):
        return _get_schema_postgres(db)
    connection = _connect(db)
    try:
        cursor = connection.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        schema = {}
        for table in tables:
            if not re.match(r"^[\w]+$", table):
                continue
            cursor.execute(f'PRAGMA table_info("{table}")')
            columns = [
                {
                    "name": row[1],
                    "type": row[2],
                    "primary_key": bool(row[5]),
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(f'PRAGMA foreign_key_list("{table}")')
            foreign_keys = [
                {
                    "column": row[3],
                    "references_table": row[2],
                    "references_column": row[4],
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(f'PRAGMA index_list("{table}")')
            indexes = [
                {"name": row[1], "unique": bool(row[2])}
                for row in cursor.fetchall()
            ]

            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            row_count = cursor.fetchone()[0]

            try:
                cursor.execute(f'SELECT * FROM "{table}" LIMIT 5')
                cols = [d[0] for d in cursor.description or []]
                sample_data = [
                    {c: _jsonable(v) for c, v in zip(cols, r)}
                    for r in cursor.fetchall()
                ]
            except Exception:  # noqa: BLE001
                sample_data = []

            schema[table] = {
                "columns": columns,
                "foreign_keys": foreign_keys,
                "indexes": indexes,
                "sample_data": sample_data,
                "row_count": row_count,
            }
        return schema
    finally:
        _close(connection, db)


def _get_schema_postgres(db):
    import psycopg2.extras
    connection = _connect(db)
    try:
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        )
        tables = [r["table_name"] for r in cursor.fetchall()]
        schema = {}
        for table in tables:
            cursor.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (table,),
            )
            columns = [
                {"name": r["column_name"], "type": r["data_type"], "primary_key": False}
                for r in cursor.fetchall()
            ]
            cursor.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename=%s",
                (table,),
            )
            indexes = [
                {"name": r["indexname"], "unique": "UNIQUE" in (r["indexdef"] or "").upper()}
                for r in cursor.fetchall()
            ]
            try:
                cursor.execute(f'SELECT COUNT(*) AS n FROM "{table}"')
                row_count = cursor.fetchone()["n"]
            except Exception:  # noqa: BLE001
                row_count = 0
            try:
                cursor.execute(f'SELECT * FROM "{table}" LIMIT 5')
                sample_data = [
                    {k: _jsonable(v) for k, v in dict(r).items()}
                    for r in cursor.fetchall()
                ]
            except Exception:  # noqa: BLE001
                sample_data = []
            schema[table] = {
                "columns": columns,
                "foreign_keys": [],
                "indexes": indexes,
                "sample_data": sample_data,
                "row_count": row_count,
            }
        return schema
    finally:
        _close(connection, db)


# ==================================================================
# TOOL 2 - EXECUTE QUERY
# ==================================================================

def execute_query(sql, db="grocery"):
    """
    Execute a SQL SELECT query against the database.

    Args:
        sql: SQL SELECT statement.
        db: database name (default 'grocery').

    Returns:
        {"success": bool, "row_count": int, "columns": [...],
         "data": [...]} or an error object.
    """
    statement = sql.strip()
    # Strip a single wrapping paren pair: "(SELECT ...)" -> "SELECT ..."
    if statement.startswith("(") and statement.endswith(")"):
        statement = statement[1:-1].strip()
    # Drop trailing semicolons: LLMs habitually terminate queries with ";"
    # but the safety guard below rejects ";" (multi-statement protection).
    # Interior semicolons are still rejected, so this stays read-only.
    statement = statement.rstrip(";").strip()
    lowered = statement.lower()

    if not lowered.startswith("select") and not lowered.startswith("with"):
        return {
            "success": False,
            "error": "Only SELECT queries are allowed for safety.",
        }
    if _FORBIDDEN.search(statement):
        return {
            "success": False,
            "error": "Only single read-only SELECT statements are allowed.",
        }

    try:
        connection = _connect(db)
        try:
            cursor = connection.cursor()
            start = time.perf_counter()
            cursor.execute(statement)
            columns = [d[0] for d in cursor.description or []]
            fetched = cursor.fetchmany(MAX_QUERY_ROWS + 1)
            # Normalize RealDict-style rows to tuples if needed
            if fetched and isinstance(fetched[0], dict):
                rows = [tuple(r[c] for c in columns) for r in fetched]
            else:
                rows = list(fetched)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        finally:
            _close(connection, db)

        truncated = len(rows) > MAX_QUERY_ROWS
        data = [
            {col: _jsonable(value) for col, value in zip(columns, row)}
            for row in rows[:MAX_QUERY_ROWS]
        ]

        return {
            "success": True,
            "row_count": len(data),
            "truncated": truncated,
            "columns": columns,
            "data": data,
            "rows": data,
            "execution_time_ms": elapsed_ms,
            "rows_per_second": round(len(data) / max(elapsed_ms / 1000, 0.001), 0),
        }

    except Exception as error:  # noqa: BLE001 - surface errors to the model
        return {
            "success": False,
            "sql": sql,
            "error": str(error),
        }


def explain_plan(sql, db="grocery"):
    """
    Return the query execution plan (EXPLAIN QUERY PLAN on SQLite,
    EXPLAIN on Postgres) plus a performance class hint.

    Args:
        sql: SQL SELECT statement.
        db: database name.
    """
    statement = (sql or "").strip().rstrip(";").strip()
    if not statement.lower().lstrip("(").startswith(("select", "with")):
        return {"success": False, "error": "Only SELECT queries can be explained."}
    if _FORBIDDEN.search(statement):
        return {"success": False, "error": "Query blocked by safety guard."}
    try:
        connection = _connect(db)
        try:
            cursor = connection.cursor()
            if _is_postgres(db):
                cursor.execute("EXPLAIN " + statement)
                plan = [" ".join(str(c) for c in r) for r in cursor.fetchall()]
            else:
                cursor.execute("EXPLAIN QUERY PLAN " + statement)
                plan = [" | ".join(str(c) for c in r) for r in cursor.fetchall()]
            return {"success": True, "plan": plan[:20]}
        finally:
            _close(connection, db)
    except Exception as error:  # noqa: BLE001
        return {"success": False, "error": str(error), "sql": sql}


# ==================================================================
# TOOL 3 - GENERATE CHART
# ==================================================================

def generate_chart(
    data,
    chart_type,
    x_column,
    y_column=None,
    title="Chart",
):
    """
    Generate an interactive Plotly chart from query results.

    Args:
        data: list of dictionaries (query results).
        chart_type: 'bar', 'line', 'pie' or 'scatter'.
        x_column: column used as X axis / categories / names.
        y_column: numeric column for the Y axis (not used by pie).
        title: chart title.

    Returns:
        Dictionary with a Plotly figure spec ('figure') the
        frontend renders with plotly.js, plus a saved HTML file.
    """
    if not data:
        return {"success": False, "error": "No data available to chart."}

    rows = list(data)
    categories = {"bar", "line", "pie", "scatter", "histogram", "box", "heatmap"}

    if chart_type not in categories:
        return {
            "success": False,
            "error": "Unsupported chart type. Use bar, line, pie, scatter, histogram, box or heatmap.",
        }

    if chart_type == "heatmap":
        return _heatmap_chart(rows, title)

    if x_column not in rows[0]:
        return {
            "success": False,
            "error": f"Column '{x_column}' not found in result data.",
        }

    if chart_type in ("histogram", "box"):
        pass  # single-column distribution charts; validated below
    elif chart_type != "pie":
        if y_column is None or y_column not in rows[0]:
            return {
                "success": False,
                "error": f"Column '{y_column}' not found in result data.",
            }
    else:
        # Pie needs a values column: use y_column if valid, else first
        # numeric column that isn't x_column.
        if y_column not in rows[0]:
            numeric = [
                k for k, v in rows[0].items()
                if k != x_column and isinstance(v, (int, float))
                and not isinstance(v, bool)
            ]
            if not numeric:
                return {
                    "success": False,
                    "error": "Pie chart needs a numeric values column.",
                }
            y_column = numeric[0]

    try:
        import plotly.express as px  # lazy: cuts cold start by ~10s

        if chart_type == "bar":
            # One vivid color per category (with legend), MITRA-style.
            figure = px.bar(
                rows, x=x_column, y=y_column, title=title,
                color=x_column, color_discrete_sequence=CHART_COLORS,
            )
        elif chart_type == "line":
            figure = px.line(rows, x=x_column, y=y_column, title=title,
                             markers=True)
        elif chart_type == "pie":
            figure = px.pie(
                rows, names=x_column, values=y_column, title=title,
                color_discrete_sequence=CHART_COLORS,
            )
        elif chart_type == "histogram":
            figure = px.histogram(rows, x=x_column, nbins=30, title=title)
        elif chart_type == "box":
            figure = px.box(rows, y=y_column or x_column, title=title)
        else:
            figure = px.scatter(rows, x=x_column, y=y_column, title=title)

        figure.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"color": "#e5e7eb"},
            margin={"l": 40, "r": 20, "t": 50, "b": 40},
        )

        filepath = os.path.join(
            CHART_FOLDER, f"chart_{chart_type}_{int(time.time()*1000)}.html"
        )
        try:
            figure.write_html(filepath)
        except OSError:
            filepath = None

        return {
            "success": True,
            "chart_type": chart_type,
            "title": title,
            "figure": figure.to_json(),
            "file": filepath,
        }

    except Exception as error:  # noqa: BLE001
        return {"success": False, "error": str(error)}


def _heatmap_chart(rows, title="Correlation"):
    """Correlation heatmap of numeric columns (no x/y needed)."""
    try:
        import plotly.express as px
        numeric = [
            k for k in rows[0].keys()
            if isinstance(rows[0][k], (int, float))
            and not isinstance(rows[0][k], bool)
        ][:8]
        if len(numeric) < 2:
            return {"success": False, "error": "Heatmap needs 2+ numeric columns."}
        import pandas as pd  # lazy
        frame = pd.DataFrame(
            [{c: r.get(c) for c in numeric} for r in rows]
        ).select_dtypes(include="number")
        corr = frame.corr(numeric_only=True).fillna(0)
        figure = px.imshow(
            corr.values, x=list(corr.columns), y=list(corr.index),
            text_auto=".2f", aspect="auto", title=title, color_continuous_scale="Viridis",
        )
        figure.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"color": "#e5e7eb"},
            margin={"l": 60, "r": 20, "t": 50, "b": 60},
        )
        return {
            "success": True, "chart_type": "heatmap", "title": title,
            "figure": figure.to_json(), "file": None,
        }
    except Exception as error:  # noqa: BLE001
        return {"success": False, "error": str(error)}


if __name__ == "__main__":
    import json

    print(json.dumps(get_schema(), indent=2)[:2000])