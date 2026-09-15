"""
Streaming LLM agent (Groq preferred, OpenRouter fallback).

Uses an OpenAI-compatible chat completions API with the
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
    LLM_API_KEY,
    LLM_BASE_URL,
    available_models,
)
from backend.tool_registry import build_tool_declarations, run_tool

load_dotenv()


def get_client():
    if not LLM_API_KEY:
        raise RuntimeError(
            "LLM API key is not configured. "
            "Set GROQ_API_KEY (preferred) or OPENROUTER_API_KEY "
            "in the Vercel environment variables or .env."
        )
    return OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        max_retries=0,
    )

# ------------------------------------------------------------------
# System prompt
# ------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = """You are a data analysis agent for a SQLite database.

Your job:
1. Translate the user's natural-language question into a correct SQL SELECT query and run it with execute_query.
2. Answer with clear, concise insights backed by real numbers from the results.
3. When the user asks to see or visualize data, immediately generate a chart with generate_chart (bar, line, pie, scatter, histogram, box, heatmap).
4. When the user asks for entity-relationship diagrams, process flows or workflows, create a Mermaid diagram with generate_flowchart (er / flowchart / graph / mindmap).
5. Optionally call explain_data to compute summary statistics (skew, kurtosis, IQR outliers, correlation matrix).
6. After generating SQL, call assess_query to validate the query and get a confidence score (0-10), issues, visualization recommendation and alternative queries.
7. For slow or large queries, call explain_plan to show the execution plan and performance class.

Rules:
- The schema snapshot below is already verified — use it directly, no need to call get_schema first (only call it for structure/ER questions or if a query fails on unknown columns).
- SQL must be a single read-only SELECT. Quote identifiers with double quotes, string literals with single quotes. Use LIMIT when appropriate.
- Do not invent numbers: everything you state must come from query results.
- If a query fails, fix the SQL by reasoning about the error and retry (up to 2 attempts).
- Keep explanations short and human-friendly. Use markdown bullet lists for comparisons.
- If chart/table requests have no data, say so and suggest what to ask instead.

AVAILABLE DATABASES (pass the name in the 'database' argument):
{databases}

CURRENTLY SELECTED DATABASE: {selected}

SCHEMA SNAPSHOT ({selected}):
{schema_snapshot}

IMPORTANT: Your final assistant message must end with a `decision` code
block containing ONLY valid JSON (no comments, no trailing commas, no
markdown inside strings). This block is parsed by the frontend.

Format — keep it compact, one line per array element:

```decision
{"confidence_score":8.5,"decision_log":["Step 1: translated to SQL","Step 2: ran query, 42 rows"],"alternatives":["SELECT ... LIMIT 50"],"performance":{"execution_time_ms":42,"rows_per_second":4200},"visualization":"bar"}
```

Fields:
- confidence_score: float 0-10
- decision_log: array of short step strings
- alternatives: array of alternative SQL strings (may be empty)
- performance: object with execution_time_ms, rows_per_second (may be omitted)
- visualization: "bar"|"line"|"pie"|"scatter" (may be omitted)

The code fence must start with ```decision and end with ```.
Do NOT put anything after the closing fence.
"""


# ------------------------------------------------------------------
# Conversation helpers
# ------------------------------------------------------------------

def _compact_schema(database, max_tables=12, max_cols=20):
    """Small schema snapshot injected into the system prompt (saves 1 tool turn)."""
    try:
        from backend.database_tools import get_schema as _get_schema
        schema = _get_schema(database)
    except Exception:
        return "(schema unavailable — call get_schema)"
    lines = []
    for table in sorted(schema)[:max_tables]:
        info = schema[table]
        cols = ", ".join(
            c["name"] + ("*" if c.get("primary_key") else "")
            for c in info.get("columns", [])[:max_cols]
        )
        lines.append(f"- {table}({cols}) [{info.get('row_count', '?')} rows]")
    return "\n".join(lines)[:3000] or "(empty)"


def build_messages(messages, database):
    """Convert frontend {role, content} messages into chat-completion messages."""
    database_list = "\n".join(
        f"- {name}: {info['description']}" for name, info in DATABASES.items()
    )
    system = SYSTEM_INSTRUCTIONS.format(
        databases=database_list, selected=database,
        schema_snapshot=_compact_schema(database),
    )
    chat = [{"role": "system", "content": system}]
    for message in messages[-10:]:
        role = message.get("role", "user")
        if role != "assistant":
            role = "user"
        text = str(message.get("content", ""))[:4000]
        if not text.strip():
            continue
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
            perf = ""
            if result.get("execution_time_ms"):
                perf = f" in {result['execution_time_ms']}ms"
            return (
                f"{result['row_count']} row(s) returned"
                + (" (truncated)" if result.get("truncated") else "")
                + perf
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
    if name == "explain_plan":
        if result.get("success"):
            return "Execution plan retrieved"
        return f"Explain failed: {result.get('error', 'unknown error')}"
    if name == "assess_query":
        if result.get("success"):
            return f"Confidence: {result.get('confidence', '?')}/10"
        return "Assessment failed"
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
                if call.get("id") and call.get("name")
            ]
            # If streaming produced incomplete tool calls (no id), skip this turn.
            if not tool_calls:
                continue
            assistant_message["tool_calls"] = tool_calls
            chat.append(assistant_message)

            # Execute the requested tools
            for call in calls.values():
                call_id = call.get("id")
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
                        "execution_time_ms": result.get("execution_time_ms"),
                        "rows_per_second": result.get("rows_per_second"),
                    })

                yield event("tool_result", result_event)

                # Feed the function response back to the model
                # tool_call_id must be the string id returned by the model
                # (e.g. "call_abc123"), NOT the numeric stream index.
                if not call_id:
                    continue
                chat.append({
                    "role": "tool",
                    "tool_call_id": str(call_id),
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

            # NOTE: do NOT reset total_text here — it must accumulate
            # across tool turns so the final "done" contains the full answer.

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