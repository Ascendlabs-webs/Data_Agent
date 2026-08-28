"""
Streaming LLM agent backed by OpenRouter.

Uses OpenRouter's OpenAI-compatible chat completions API with the
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
import time

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI

from backend.config import (
    DATABASES,
    MAX_TOOL_TURNS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    available_models,
)
from backend.tool_registry import build_tool_declarations, run_tool

load_dotenv()


def get_client():
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured. "
            "Set it in the Vercel environment variables or .env."
        )
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        max_retries=0,
    )

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

def build_messages(messages, database):
    """Convert frontend {role, content} messages into chat-completion messages."""
    database_list = "\n".join(
        f"- {name}: {info['description']}" for name, info in DATABASES.items()
    )
    system = SYSTEM_INSTRUCTIONS.format(
        databases=database_list, selected=database
    )
    chat = [{"role": "system", "content": system}]
    for message in messages[-20:]:
        role = message.get("role", "user")
        if role != "assistant":
            role = "user"
        text = message.get("content", "")
        chat.append({"role": role, "content": text})
    if chat[-1]["role"] != "user":
        chat.append({"role": "user", "content": "Hello"})
    return chat


def _error_code(error):
    """Map an OpenAI SDK exception to an HTTP status code (or None)."""
    if isinstance(error, APIStatusError):
        return error.status_code
    if isinstance(error, APIConnectionError):
        # Transient network failure (e.g. cold start) - treat as retryable.
        return 503
    return None


# ------------------------------------------------------------------
# Event helpers
# ------------------------------------------------------------------

def event(event_type, payload):
    """Serialize one event."""
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
# Model turn: stream one completion, collecting text + tool calls
# ------------------------------------------------------------------

def _stream_turn(chat, tools):
    """
    Stream a completion through the OpenRouter model chain.

    Yields 'delta' + retry/fallback 'tool_result' events, and returns
    a tuple via StopIteration: (assistant_text, {index: tool_call}).
    """
    models = available_models()

    for model_index, model in enumerate(models):
        for attempt in range(2):
            text_parts = []
            calls = {}
            try:
                client = get_client()
                stream = client.chat.completions.create(
                    model=model,
                    messages=chat,
                    tools=tools,
                    tool_choice="auto",
                    stream=True,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    if delta:
                        if delta.content:
                            text_parts.append(delta.content)
                            yield event("delta", {"text": delta.content})
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                entry = calls.setdefault(
                                    idx, {"id": None, "name": None, "arguments": ""}
                                )
                                if tc.id:
                                    entry["id"] = tc.id
                                if tc.function:
                                    if tc.function.name:
                                        entry["name"] = tc.function.name
                                    if tc.function.arguments:
                                        entry["arguments"] += tc.function.arguments
                return ("".join(text_parts), calls)
            except Exception as error:  # noqa: BLE001 - provider outage handling
                code = _error_code(error)
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
                yield event("tool_result", {
                    "name": "rate_limit",
                    "status": "waiting",
                    "summary": (
                        f"Model busy (HTTP {code}) — retrying in 3s "
                        f"(attempt {attempt + 1}/2)"
                    ),
                })
                time.sleep(3)


# ------------------------------------------------------------------
# Main streaming loop
# ------------------------------------------------------------------

def stream_chat(messages, database="grocery"):
    """
    Generator yielding event dictionaries for one user message.

    Args:
        messages: [{role, content}, ...] conversation so far.
        database: currently selected database name.

    Yields:
        dict events: delta / sql / tool / chart / diagram / table /
                     done / error
    """
    chat = build_messages(messages, database)
    tools = build_tool_declarations()

    total_text = ""
    query_attempts = 0

    for _ in range(MAX_TOOL_TURNS):
        try:
            # Drive the streaming turn generator and capture its result.
            turn = _stream_turn(chat, tools)
            while True:
                try:
                    event_item = next(turn)
                except StopIteration as exc:
                    text, calls = exc.value
                    break
                yield event_item

            total_text += text

            if not calls:
                yield event("done", {"text": total_text})
                return

            # Append the assistant turn with its tool calls.
            assistant_message = {"role": "assistant", "content": text or None}
            tool_calls = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": call["arguments"] or "{}",
                    },
                }
                for call in calls.values()
            ]
            assistant_message["tool_calls"] = tool_calls
            chat.append(assistant_message)

            # Execute the requested tools
            for call_id, call in calls.items():
                name = call["name"]
                args = json.loads(call.get("arguments") or "{}")

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
                chat.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result),
                })

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