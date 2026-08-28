import os
import json
from dotenv import load_dotenv
from google import genai

from backend.database_tools import (
    get_schema,
    execute_query,
    generate_chart
)

from backend.diagram_tools import generate_flowchart

from backend.explanation_tools import explain_data


# Load environment variables
load_dotenv()


# Create Gemini client
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
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
# GEMINI AGENT
# ==========================================

def ask_agent(user_message):

    response = client.models.generate_content(
        model="gemini-3.7-flash",
        contents=user_message,
        config={
            "tools": [
                schema_tool,
                query_tool,
                chart_tool,
                diagram_tool,
                explanation_tool
            ]
        }
    )

    return response.text


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

    print("\nGemini:")
    print(answer)