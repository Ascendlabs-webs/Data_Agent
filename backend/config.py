"""
Central configuration for the Data AI Agent.

Loads environment variables from .env and registers available
databases so the agent can connect to multiple databases at once.
"""
import os

from dotenv import load_dotenv

# Load environment variables from backend/.env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ------------------------------------------------------------------
# LLM settings (OpenAI-compatible API: Groq preferred, OpenRouter fallback)
#
# Groq is much faster (10-15s vs 90s) and still free.
# Set GROQ_API_KEY in Vercel / .env. Old OPENROUTER_* vars still work.
# ------------------------------------------------------------------

_GROQ_KEY = os.getenv("GROQ_API_KEY", "")
_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Prefer Groq when its key is present.
LLM_API_KEY = _GROQ_KEY or _OPENROUTER_KEY

if _GROQ_KEY:
    _DEFAULT_BASE = "https://api.groq.com/openai/v1"
    _DEFAULT_MODEL = "openai/gpt-oss-120b"
    _DEFAULT_FALLBACKS = "openai/gpt-oss-20b,qwen/qwen3.8-27b"
    LLM_BASE_URL = os.getenv("GROQ_BASE_URL", _DEFAULT_BASE)
    LLM_MODEL = os.getenv("GROQ_MODEL", _DEFAULT_MODEL)
    _fallback_raw = os.getenv(
        "GROQ_FALLBACK_MODELS",
        os.getenv("OPENROUTER_FALLBACK_MODELS", _DEFAULT_FALLBACKS),
    )
else:
    _DEFAULT_BASE = "https://openrouter.ai/api/v1"
    _DEFAULT_MODEL = "nvidia/nemotron-3.5-lightning:free"
    _DEFAULT_FALLBACKS = (
        "dots-studio/dots-3-note-preview:free,google/gemma-4-31b-it:free"
    )
    LLM_BASE_URL = os.getenv("OPENROUTER_BASE_URL", _DEFAULT_BASE)
    LLM_MODEL = os.getenv("OPENROUTER_MODEL", _DEFAULT_MODEL)
    _fallback_raw = os.getenv("OPENROUTER_FALLBACK_MODELS", _DEFAULT_FALLBACKS)

# Comma-separated fallback models tried when the primary model is
# unavailable (429 rate limit / 503 high demand on the provider side).
LLM_FALLBACK_MODELS = [
    m.strip() for m in _fallback_raw.split(",") if m.strip()
]

# Backwards-compat aliases (old code imports OPENROUTER_*).
OPENROUTER_API_KEY = LLM_API_KEY
OPENROUTER_BASE_URL = LLM_BASE_URL
OPENROUTER_MODEL = LLM_MODEL
OPENROUTER_FALLBACK_MODELS = LLM_FALLBACK_MODELS


def available_models():
    """Primary model followed by fallbacks, de-duplicated."""
    models = [LLM_MODEL] + LLM_FALLBACK_MODELS
    seen = set()
    result = []
    for model in models:
        if model not in seen:
            seen.add(model)
            result.append(model)
    return result

# Maximum number of tool-calling turns before the agent stops
MAX_TOOL_TURNS = 8

# Maximum rows returned by a single query (keeps responses fast)
MAX_QUERY_ROWS = 250

# ------------------------------------------------------------------
# Database registry (multi-database support)
#
# Each entry maps a database name to the SQLite file on disk.
# Add new SQLite databases here to let the agent talk to them.
# ------------------------------------------------------------------

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)


def _find_database_file():
    """Locate database/grocery_store.db by walking up parent folders."""
    cursor = BACKEND_DIR
    while True:
        candidate = os.path.join(cursor, "database", "grocery_store.db")
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(cursor)
        if parent == cursor:
            return None
        cursor = parent


DATABASES = {
    "grocery": {
        "path": _find_database_file()
        or os.path.join(PROJECT_ROOT, "database", "grocery_store.db"),
        "description": (
            "E-commerce grocery store with customers, suppliers, "
            "products, orders, order_items and inventory."
        ),
    },
}


def database_path(name):
    """Resolve a database name to its file path, or None if unknown."""
    entry = DATABASES.get(name)
    if entry is None:
        return None
    return entry["path"]


def database_names():
    """Return the list of registered database names."""
    return list(DATABASES.keys())