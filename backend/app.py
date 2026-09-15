"""
Data AI Agent - FastAPI application.

Serves the chat frontend, streams chat completions over SSE and
exposes endpoints for schema discovery, raw SQL execution, database
listing and query history/favorites.
"""
from pathlib import Path
import json
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.agent import stream_chat
from backend.config import DATABASES, database_names
from backend.database_tools import execute_query, get_schema
from backend.history_store import (
    add_entry,
    delete_entry,
    list_entries,
    set_favorite,
)

BACKEND_DIR = Path(__file__).parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

app = FastAPI(title="Data AI Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    messages: list = Field(default_factory=list)
    database: str = "grocery"


class QueryRequest(BaseModel):
    sql: str = Field(max_length=8000)
    database: str = "grocery"


# ------------------------------------------------------------------
# Simple in-memory rate limit (per IP): 40 chat reqs / minute.
# Protects the LLM key from accidental burn. Resets on redeploy.
# ------------------------------------------------------------------

_RATE: dict = {}

def _rate_limited(request: Request, limit: int = 40, window: int = 60) -> bool:
    try:
        ip = request.client.host if request.client else "unknown"
    except Exception:
        ip = "unknown"
    now = time.time()
    bucket = _RATE.setdefault(ip, [])
    while bucket and bucket[0] <= now - window:
        bucket.pop(0)
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def _resolve_db(name: str) -> str:
    return name if name in database_names() else "grocery"


def _validate_chat(request: ChatRequest):
    if not request.messages or not any(
        (m or {}).get("content") for m in request.messages
    ):
        raise HTTPException(status_code=400, detail="No message provided.")


def _sse(event: dict) -> bytes:
    return ("data: " + json.dumps(event) + "\n\n").encode("utf-8")


# ------------------------------------------------------------------
# Chat (JSON for backwards-compat + SSE stream for live tokens)
# ------------------------------------------------------------------

@app.post("/api/chat")
def chat(request: ChatRequest, raw: Request = None):
    """Run the agent and return the full event stream as a single JSON response."""
    _validate_chat(request)
    if raw is not None and _rate_limited(raw):
        raise HTTPException(status_code=429, detail="Too many requests. Wait a minute and retry.")
    events = list(stream_chat(request.messages, database=_resolve_db(request.database)))
    return {"events": events}


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest, raw: Request = None):
    """Same agent loop, streamed as Server-Sent Events for instant UI."""
    _validate_chat(request)
    if raw is not None and _rate_limited(raw):
        raise HTTPException(status_code=429, detail="Too many requests. Wait a minute and retry.")
    database = _resolve_db(request.database)
    messages = request.messages

    def gen():
        try:
            for ev in stream_chat(messages, database=database):
                yield _sse(ev)
        except Exception as error:  # noqa: BLE001
            yield _sse({"type": "error", "message": str(error)})

    return StreamingResponse(gen(), media_type="text/event-stream")


class HistoryRequest(BaseModel):
    question: str
    sql: str = ""
    database: str = "grocery"


# ------------------------------------------------------------------
# Databases & schema
# ------------------------------------------------------------------

@app.get("/api/databases")
def databases():
    """List databases the agent can connect to."""
    return [
        {"name": name, "description": info["description"]}
        for name, info in DATABASES.items()
    ]


@app.get("/api/schema")
def schema(database: str = "grocery"):
    """JSON schema representation of a database."""
    return get_schema(database)


@app.post("/api/query")
def query(request: QueryRequest):
    """Run a raw SQL SELECT (used by 'run this query' in the UI)."""
    return execute_query(request.sql, request.database)


# ------------------------------------------------------------------
# History & favorites
# ------------------------------------------------------------------

@app.get("/api/history")
def history(favorites_only: bool = False, database: str = None):
    return list_entries(favorites_only=favorites_only, database=database)


@app.post("/api/history")
def save_history(request: HistoryRequest):
    return add_entry(
        question=request.question,
        sql=request.sql,
        database=request.database,
    )


@app.patch("/api/history/{entry_id}")
def favorite_history(entry_id: str, favorite: bool = True):
    entry = set_favorite(entry_id, favorite)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return entry


@app.delete("/api/history/{entry_id}")
def remove_history(entry_id: str):
    if not delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found.")
    return {"deleted": True}


# ------------------------------------------------------------------
# Frontend
# ------------------------------------------------------------------

@app.get("/")
def index():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse(
            {"error": "Frontend not found. This deployment may be API-only."},
            status_code=404,
        )
    return FileResponse(index_path)


# Mount static files only if the frontend directory exists.
# On Vercel the bundle includes the frontend/ directory; guard against
# misconfigured builds where the path does not resolve correctly.
try:
    if FRONTEND_DIR.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(FRONTEND_DIR)),
            name="static",
        )
except Exception:  # noqa: BLE001 – non-fatal; API still works
    pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)