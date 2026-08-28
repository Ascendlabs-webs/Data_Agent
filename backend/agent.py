"""
Streaming LLM agent.

Runs the Gemini model with the five database tools using the
function-calling loop, and yields structured events so the
frontend can stream tokens and render tool artefacts live:

    delta   -> streaming text chunk
    sql     -> generated SQL (SQL transparency)
    tool    -> tool started / finished
    chart   -> Plotly figure JSON
    diagram -> Mermaid source
    table   -> query result preview
    done    -> final assistant message
    error   -> failure message
"""
import json
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors
from google.genai import types

from backend.config import (
    DATABASES,
    GEMINI_API_KEY,
    MAX_TOOL_TURNS,
    available_models,
)
from backend.tool_registry import build_tool_declarations, run_tool

load_dotenv()


def get_client():
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in Vercel environment variables."
        )
    return genai.Client(api_key=GEMINI_API_KEY)

# ------------------------------------------------------------------
# System prompt
# ------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = """You are a data analysis agent for a SQLite database.

Your job:
1. Translate the user's natural-language question into a correct SQL SELECT query and run it with execute_query.
2. Answer with clear, concise insights backed by real numbers from the results.
3. When the user asks to see or visualize data, immediately generate a chart with generate_chart (bar for categories, line for trends over time, pie for proportions, scatter for correlation).
4. When the user asks for entity-relationship diagrams, process flows or workflows, create a Mermaid diagram with generate_flowchart (er / flowchart / graph / mindmap).
5. Optionally call explain_data to compute summary statistics.

Rules:
- Always verify the schema with get_schema before writing SQL for an unfamiliar database.
- SQL must be a single read-only SELECT. Quote identifiers with double quotes, string literals with single quotes. Use LIMIT when appropriate.
- Do not invent numbers: everything you state must come from query results.
- If a query fails, fix the SQL by reasoning about the error and retry (up to 2 attempts).
- Keep explanations short and human-friendly. Use markdown bullet lists for comparisons.
- If chart/table requests have no data, say so and suggest what to ask instead.

AVAILABLE DATABASES (pass the name in the 'database' argument):
{databases}

CURRENTLY SELECTED DATABASE: {selected}"""


# ------------------------------------------------------------------
# Conversation helpers
# ------------------------------------------------------------------

def build_contents(messages, database):
    """Convert frontend {role, content} messages into Gemini contents."""
    contents = []
    for message in messages[-20:]:
        role = message.get("role", "user")
        text = message.get("content", "")
        if role == "assistant":
            role = "model"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=text)])
        )
    if not contents or contents[-1].role != "user":
        contents.append(
            types.Content(role="user", parts=[types.Part(text="Hello")]
        ))
    return contents


def build_config(database):
    """Build the GenerateContentConfig with tools for this session."""
    database_list = "\n".join(
        f"- {name}: {info['description']}" for name, info in DATABASES.items()
    )
    system = SYSTEM_INSTRUCTIONS.format(
        databases=database_list, selected=database
    )
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=[
            types.Tool(
                function_declarations=build_tool_declarations()
            )
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    )
    return config


def _chunk_candidates(chunk):
    """Candidates from a streamed chunk, tolerating dict responses."""
    if isinstance(chunk, dict):
        return chunk.get("candidates") or []
    return chunk.candidates or []


def _chunk_text(chunk):
    """Text from a streamed chunk, tolerating dict responses."""
    if isinstance(chunk, dict):
        return chunk.get("text") or ""
    return chunk.text or ""


def extract_function_calls(chunks):
    """Collect function calls from a streamed response."""
    calls = []
    for chunk in chunks:
        for candidate in _chunk_candidates(chunk):
            content = getattr(candidate, "content", None)
            if content is None:
                continue
            for part in content.parts:
                if part.function_call:
                    calls.append(part.function_call)
        attribute_calls = (
            chunk.get("function_calls")
            if isinstance(chunk, dict)
            else getattr(chunk, "function_calls", None)
        ) or []
        for call in attribute_calls:
            if call not in calls:
                calls.append(call)
    return calls


def chunk_has_function_calls(chunk):
    """True if this streamed chunk carries a function call part."""
    for candidate in _chunk_candidates(chunk):
        content = getattr(candidate, "content", None)
        if content and any(p.function_call for p in content.parts):
            return True
    return False


# ------------------------------------------------------------------
# Event helpers
# ------------------------------------------------------------------

def event(event_type, payload):
    """Serialize one SSE event."""
    return {
        "type": event_type,
        **payload,
    }


def summarize_tool_result(name, result):
    """Create a compact summary of a tool result for the UI."""
    if name == "execute_query":
        if result.get("success"):
            return (
                f"{result['row_count']} row(s) returned"
                + (" (truncated)" if result.get("truncated") else "")
            )
        return f"Query failed: {result.get('error', 'unknown error')}"
    if name == "generate_chart":
        if result.get("success"):
            return f"{result['chart_type'].title()} chart created"
        return f"Chart failed: {result.get('error', 'unknown error')}"
    if name == "generate_flowchart":
        if result.get("success"):
            return f"{result['diagram_type']} diagram created"
        return f"Diagram failed: {result.get('error', 'unknown error')}"
    if name == "get_schema":
        return "Schema retrieved"
    if name == "explain_data":
        return "Data summarized"
    return "Tool executed"

# ------------------------------------------------------------------
# Main streaming loop
# ------------------------------------------------------------------

def _retry_delay(error_message):
    """Extract the API-recommended retry delay from a 429 message."""
    match = re.search(r'"retryDelay":\s*"?(\d+(?:\.\d+)?)s"?', str(error_message))
    if match:
        return float(match.group(1)) + 2
    return 30


def _stream_generate(contents, config):
    """Generate content, failing over to fallback models on 429/503 quickly."""
    models = available_models()
    for model_index, model in enumerate(models):
        for attempt in range(2):
            try:
                client = get_client()
                for chunk in client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=config,
                ):
                    yield chunk
                return
            except (errors.ClientError, errors.ServerError) as error:
                code = getattr(error, "code", None)
                if code not in (429, 503):
                    raise
                is_last_model = model_index == len(models) - 1
                if attempt == 1 or is_last_model:
                    if is_last_model:
                        raise
                    yield event("tool_result", {
                        "name": "rate_limit",
                        "status": "fallback",
                        "summary": (
                            f"Model '{model}' unavailable (HTTP {code}) — "
                            f"switching to fallback model."
                        ),
                    })
                    break
                delay = _retry_delay(str(error)) if code == 429 else 3
                yield event("tool_result", {
                    "name": "rate_limit",
                    "status": "waiting",
                    "summary": (
                        f"Model busy (HTTP {code}) — retrying in {int(delay)}s "
                        f"(attempt {attempt + 1}/2)"
                    ),
                })
                time.sleep(delay)


def stream_chat(messages, database="grocery"):
    """
    Generator yielding SSE event dictionaries for one user message.

    Args:
        messages: [{role, content}, ...] conversation so far.
        database: currently selected database name.

    Yields:
        dict events: delta / sql / tool / chart / diagram / table /
                     done / error
    """
    config = build_config(database)
    contents = build_contents(messages, database)

    total_text = ""
    query_attempts = 0

    for _ in range(MAX_TOOL_TURNS):
        try:
            chunks = []
            for chunk in _stream_generate(contents, config):
                chunks.append(chunk)
                if chunk_has_function_calls(chunk):
                    continue
                text = _chunk_text(chunk)
                if text:
                    total_text += text
                    yield event("delta", {"text": text})

            function_calls = extract_function_calls(chunks)

            if not function_calls:
                yield event("done", {"text": total_text})
                return

            # Append the model turn with its function calls.
            # Use the streamed content as-is to preserve thought
            # signatures required by the API.
            model_content = None
            for chunk in reversed(chunks):
                for candidate in _chunk_candidates(chunk):
                    content = getattr(candidate, "content", None)
                    if content and any(
                        part.function_call for part in content.parts
                    ):
                        model_content = content
                        break
                if model_content is not None:
                    break
            if model_content is None:
                model_content = types.Content(
                    role="model",
                    parts=[types.Part(text=total_text)] if total_text else [],
                )
            contents.append(model_content)

            # Execute the requested tools
            for call in function_calls:
                name = call.name
                args = dict(call.args or {})
                call_id = getattr(call, "id", None)

                yield event("tool", {
                    "name": name,
                    "args": json.dumps(args)[:2000],
                    "status": "running",
                })

                # SQL transparency: surface generated SQL before execution
                if name == "execute_query":
                    yield event("sql", {"sql": args.get("sql", "")})

                result = run_tool(name, args, database=database)

                result_event = {
                    "name": name,
                    "status": "done",
                    "summary": summarize_tool_result(name, result),
                }

                if name == "generate_chart" and result.get("success"):
                    result_event.update({
                        "chart": json.loads(result["figure"]),
                        "title": result.get("title", "Chart"),
                        "chart_type": result.get("chart_type"),
                    })
                elif name == "generate_flowchart" and result.get("success"):
                    result_event.update({
                        "diagram": result.get("mermaid_code"),
                        "title": result.get("title", "Diagram"),
                        "diagram_type": result.get("diagram_type"),
                    })
                elif name == "execute_query" and result.get("success"):
                    result_event.update({
                        "columns": result.get("columns", []),
                        "rows": result.get("data", []),
                        "row_count": result.get("row_count", 0),
                    })

                yield event("tool_result", result_event)

                # Feed the function response back to the model
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=name,
                                response=result,
                            )
                        ],
                    )
                )

                if not result.get("success") and name == "execute_query":
                    query_attempts += 1
                    if query_attempts >= 2:
                        yield event("done", {
                            "text": (
                                total_text or
                                "I could not execute that query. "
                                f"Error: {result.get('error')}"
                            )
                        })
                        return

            # Reset the accumulated text for the next model turn
            total_text = ""

        except Exception as error:  # noqa: BLE001 - graceful fallback
            yield event("error", {
                "message": (
                    "Something went wrong while talking to the model: "
                    f"{error}"
                )
            })
            return

    yield event("done", {"text": total_text or "Done (max tool turns reached)."})


if __name__ == "__main__":
    for item in stream_chat(
        [{"role": "user", "content": "Show me the top 5 products by revenue this quarter"}]
    ):
        print(item["type"], json.dumps(item)[:300])
