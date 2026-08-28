import os
import json
from dotenv import load_dotenv
from openai import OpenAI

from backend.database_tools import (
    get_schema,
    execute_query,
    generate_chart
)

from backend.diagram_tools import generate_flowchart

from backend.explanation_tools import explain_data


# Load environment variables
load_dotenv()


# Create OpenRouter client (OpenAI-compatible)
client = OpenAI(
    base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    api_key=os.getenv("OPENROUTER_API_KEY")
)


# ==========================================
# TOOL 1 - GET DATABASE SCHEMA
# ==========================================

def schema_tool():
    """
    Get the complete structure of the grocery store database.

    Returns tables, columns, data types,
    primary keys and foreign keys.
    """

    return get_schema()


# ==========================================
# TOOL 2 - EXECUTE SQL
# ==========================================

def query_tool(sql: str):
    """
    Execute a SQL SELECT query on the grocery database.

    Args:
        sql: SQL SELECT query.

    Returns:
        Query results.
    """

    return execute_query(sql)


# ==========================================
# TOOL 3 - GENERATE CHART
# ==========================================

def chart_tool(
    data_json: str,
    chart_type: str,
    x_column: str,
    y_column: str = None,
    title: str = "Grocery Store Chart"
):
    """
    Generate a chart from database results.

    data_json must contain a JSON array of objects.
    """

    data = json.loads(data_json)

    return generate_chart(
        data=data,
        chart_type=chart_type,
        x_column=x_column,
        y_column=y_column,
        title=title
    )


# ==========================================
# TOOL 4 - GENERATE FLOWCHART
# ==========================================

def diagram_tool(
    diagram_type: str,
    title: str,
    content: str
):
    """
    Generate an ER diagram or process flowchart.

    diagram_type can be:
    er or flowchart.
    """

    return generate_flowchart(
        diagram_type=diagram_type,
        title=title,
        content=content
    )


# ==========================================
# TOOL 5 - EXPLAIN DATA
# ==========================================

def explanation_tool(data_json: str):
    """
    Explain database query results in simple language.

    data_json must contain a JSON array of objects.
    """

    data = json.loads(data_json)

    return explain_data(data)


# ==========================================
# OPENROUTER AGENT
# ==========================================

def ask_agent(user_message):

    response = client.chat.completions.create(
        model=os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning"),
        messages=[
            {"role": "user", "content": user_message}
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_schema",
                    "description": "Get database schema",
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_query",
                    "description": "Execute a SQL SELECT query",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string"}
                        },
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_chart",
                    "description": "Generate a chart",
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_flowchart",
                    "description": "Generate a flowchart",
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "explain_data",
                    "description": "Explain query results",
                },
            },
        ],
    )

    return response.choices[0].message.content


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":

    print("===================================")
    print(" Grocery Store AI Agent")
    print("===================================")

    question = input(
        "\nAsk your database a question: "
    )

    answer = ask_agent(question)

    print("\nAgent:")
    print(answer)