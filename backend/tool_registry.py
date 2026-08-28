"""
Tool registry: the five agent tools exposed to the LLM.

Each tool function is documented with type hints and a Google-style
docstring so the Gemini SDK can build function declarations from them.
"""
import json

from backend.database_tools import execute_query as _execute_query
from backend.database_tools import generate_chart as _generate_chart
from backend.database_tools import get_schema as _get_schema
from backend.diagram_tools import generate_diagram
from backend.explanation_tools import explain_data as _explain_data


# ==================================================================
# TOOL 1 - GET SCHEMA
# ==================================================================

def get_schema(database: str = "grocery"):
    """
    Retrieve the database schema: every table with its columns,
    primary keys, foreign keys and row counts.

    Call this when you need to understand the tables available
    before writing SQL, or to answer questions about the database
    structure (e.g. ER-diagram requests).

    Args:
        database: database name (default 'grocery').
    """
    return _get_schema(database)


# ==================================================================
# TOOL 2 - EXECUTE QUERY
# ==================================================================

def execute_query(sql: str, database: str = "grocery"):
    """
    Execute a read-only SQL SELECT query and return the results.

    Use double quotes around identifiers and single quotes around
    string literals. Only SELECT statements are permitted.

    Args:
        sql: the complete SQL SELECT statement to run.
        database: database name (default 'grocery').
    """
    return _execute_query(sql, database)


# ==================================================================
# TOOL 3 - GENERATE CHART
# ==================================================================

def generate_chart(
    data_json: str,
    chart_type: str,
    x_column: str,
    y_column: str = None,
    title: str = "Chart",
):
    """
    Generate an interactive chart from query results and render it
    in the chat for the user to see.

    Call this after execute_query whenever the user asks to see the
    data as a bar, line, pie or scatter chart.

    Args:
        data_json: the query results as a JSON array of objects
                   (pass the 'data' array from execute_query).
        chart_type: 'bar' for categorical comparisons, 'line' for
                    trends over time, 'pie' for proportional
                    distribution, 'scatter' for correlation.
        x_column: column name used for the X axis / categories.
        y_column: numeric column used for the Y axis.
        title: chart title.
    """
    data = json.loads(data_json)
    return _generate_chart(data, chart_type, x_column, y_column, title)


# ==================================================================
# TOOL 4 - GENERATE FLOWCHART
# ==================================================================

def generate_flowchart(
    diagram_type: str,
    title: str,
    content: str,
):
    """
    Generate and render a diagram in the chat.

    Use 'er' for entity-relationship diagrams of database tables,
    'flowchart' for process/data-pipeline flows, 'graph' for
    generic directed graphs, 'mindmap' for hierarchies.

    Args:
        diagram_type: 'er', 'flowchart', 'graph' or 'mindmap'.
        title: short title displayed above the diagram.
        content: Mermaid source code. Must start with the matching
                 keyword: 'erDiagram', 'flowchart TD', 'graph LR'
                 or 'mindmap'.
    """
    return generate_diagram(diagram_type, title, content)


# ==================================================================
# TOOL 5 - EXPLAIN DATA
# ==================================================================

def explain_data(data_json: str):
    """
    Compute a quick statistical summary (counts, min/max/avg,
    most common categories) of query results.

    Call this to back up your insights with numbers.

    Args:
        data_json: the query results as a JSON array of objects
                   (pass the 'data' array from execute_query).
    """
    data = json.loads(data_json)
    return _explain_data(data)


# ------------------------------------------------------------------
# Manual function declarations (deterministic tool schemas)
# ------------------------------------------------------------------

def build_tool_declarations():
    """
    Return the OpenAI-format 'tools' schemas sent to the model
    via OpenRouter's OpenAI-compatible chat completions API.

    Using explicit schemas (instead of callable introspection) makes
    tool definitions deterministic and provider-independent.
    """
    schemas = [
        {
            "name": "get_schema",
            "description": (
                "Retrieve the database schema: every table with its "
                "columns, primary keys, foreign keys and row counts. "
                "Call before writing SQL when the database layout is "
                "unknown, or for structure questions (ER diagrams)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "database": {
                        "type": "string",
                        "description": "Database name (default 'grocery').",
                    }
                },
            },
        },
        {
            "name": "execute_query",
            "description": (
                "Execute a read-only SQL SELECT query and return results. "
                "Quote identifiers with double quotes and string literals "
                "with single quotes. Use LIMIT when appropriate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The complete SQL SELECT statement.",
                    },
                    "database": {
                        "type": "string",
                        "description": "Database name (default 'grocery').",
                    },
                },
                "required": ["sql"],
            },
        },
        {
            "name": "generate_chart",
            "description": (
                "Generate an interactive chart from query results and "
                "render it in the chat. Call after execute_query whenever "
                "the user asks to see data as a bar, line, pie or scatter "
                "chart."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_json": {
                        "type": "string",
                        "description": (
                            "Query results as a JSON array of objects "
                            "(the 'data' array from execute_query)."
                        ),
                    },
                    "chart_type": {
                        "type": "string",
                        "description": (
                            "bar (categorical comparisons), line (trends "
                            "over time), pie (proportional distribution), "
                            "scatter (correlation)."
                        ),
                    },
                    "x_column": {
                        "type": "string",
                        "description": "Column for X axis / categories.",
                    },
                    "y_column": {
                        "type": "string",
                        "description": "Numeric column for Y axis.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Chart title.",
                    },
                },
                "required": ["data_json", "chart_type", "x_column"],
            },
        },
        {
            "name": "generate_flowchart",
            "description": (
                "Generate and render a Mermaid diagram in the chat: "
                "'er' for entity-relationship diagrams of database tables, "
                "'flowchart' for process/data-pipeline flows, 'graph' for "
                "generic directed graphs, 'mindmap' for hierarchies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diagram_type": {
                        "type": "string",
                        "description": "er, flowchart, graph or mindmap.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title shown above the diagram.",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Mermaid source. Must start with the matching "
                            "keyword: erDiagram, flowchart TD, graph LR "
                            "or mindmap."
                        ),
                    },
                },
                "required": ["diagram_type", "title", "content"],
            },
        },
        {
            "name": "explain_data",
            "description": (
                "Compute a quick statistical summary (counts, min/max/avg, "
                "most common categories) of query results. Call to back up "
                "your insights with numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_json": {
                        "type": "string",
                        "description": (
                            "Query results as a JSON array of objects."
                        ),
                    }
                },
                "required": ["data_json"],
            },
        },
    ]
    return [
        {"type": "function", "function": schema}
        for schema in schemas
    ]


# ------------------------------------------------------------------
# Dispatch helpers
# ------------------------------------------------------------------

TOOLS = {
    "get_schema": get_schema,
    "execute_query": execute_query,
    "generate_chart": generate_chart,
    "generate_flowchart": generate_flowchart,
    "explain_data": explain_data,
}


def run_tool(name, args, database="grocery"):
    """
    Execute a tool by name with the given arguments.

    The selected database is injected automatically for database
    tools when the model did not specify one itself.
    """
    function = TOOLS.get(name)
    if function is None:
        return {"success": False, "error": f"Unknown tool '{name}'."}

    if name in ("get_schema", "execute_query") and "database" not in args:
        args["database"] = database

    try:
        return function(**args)
    except TypeError as error:
        return {
            "success": False,
            "error": f"Invalid arguments for {name}: {error}",
        }
    except Exception as error:  # noqa: BLE001
        return {"success": False, "error": str(error)}