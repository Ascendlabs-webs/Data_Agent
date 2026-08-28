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
# LLM settings
# ------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

# Comma-separated fallback models tried when the primary model is
# unavailable (429 rate limit / 503 high demand on Google's side).
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv(
        "GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-2.5-flash"
    ).split(",")
    if m.strip()
]

def available_models():
    """Primary model followed by fallbacks, de-duplicated."""
    models = [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS
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