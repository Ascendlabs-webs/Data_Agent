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


def _connect(db):
    """Open a read-only connection to the named database."""
    if db not in DATABASES:
        raise ValueError(
            f"Unknown database '{db}'. Available: {', '.join(DATABASES)}"
        )
    path = DATABASES[db]["path"]
    # Read-only URI: even if the SQL guard is bypassed, writes fail.
    connection = sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=10, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


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
    primary keys, foreign keys and row counts.

    Args:
        db: database name (default 'grocery').

    Returns:
        Dictionary keyed by table name.
    """
    connection = _connect(db)
    cursor = connection.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]

    schema = {}
    for table in tables:
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

        cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
        row_count = cursor.fetchone()[0]

        schema[table] = {
            "columns": columns,
            "foreign_keys": foreign_keys,
            "row_count": row_count,
        }

    connection.close()
    return schema


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
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description or []]
            rows = cursor.fetchmany(MAX_QUERY_ROWS + 1)
        finally:
            connection.close()

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
        }

    except Exception as error:  # noqa: BLE001 - surface errors to the model
        return {
            "success": False,
            "sql": sql,
            "error": str(error),
        }


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
    categories = {"bar", "line", "pie", "scatter"}

    if chart_type not in categories:
        return {
            "success": False,
            "error": "Unsupported chart type. Use bar, line, pie or scatter.",
        }

    if x_column not in rows[0]:
        return {
            "success": False,
            "error": f"Column '{x_column}' not found in result data.",
        }

    if chart_type != "pie":
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
            figure = px.bar(rows, x=x_column, y=y_column, title=title)
        elif chart_type == "line":
            figure = px.line(rows, x=x_column, y=y_column, title=title,
                             markers=True)
        elif chart_type == "pie":
            figure = px.pie(rows, names=x_column, values=y_column, title=title)
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


if __name__ == "__main__":
    import json

    print(json.dumps(get_schema(), indent=2)[:2000])