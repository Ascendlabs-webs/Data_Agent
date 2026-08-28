# 🛒 Data AI Agent — Conversational Database Analyst

> **Hackathon Submission** · Built with FastAPI + Google Gemini + Vanilla JS

An LLM-powered agent that lets non-technical users ask questions in plain English, query a SQLite database, and see the answers with interactive charts, diagrams and tables — all inside a ChatGPT-style chat interface. No SQL knowledge required.

## 🌐 Live Demo → [aids-nine.vercel.app](https://aids-nine.vercel.app/)

[![Live Demo](https://img.shields.io/badge/Live%20Demo-aids--nine.vercel.app-7c6cf0?style=for-the-badge&logo=vercel&logoColor=white)](https://aids-nine.vercel.app/)

![Python](https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)
![Gemini](https://img.shields.io/badge/Google%20Gemini-AI-7c6cf0?style=flat-square&logo=google&logoColor=white)
![Vercel](https://img.shields.io/badge/Deployed%20on-Vercel-black?style=flat-square&logo=vercel&logoColor=white)

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Screenshots](#screenshots)
- [System Architecture](#system-architecture)
- [Agent Tools](#agent-tools)
- [Streaming Protocol](#streaming-protocol)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Running Tests](#running-tests)
- [Deploying to Vercel](#deploying-to-vercel)
- [Extending — Add Your Own Database](#extending--add-your-own-database)
- [Known Limitations](#known-limitations)
- [Tech Stack](#tech-stack)

---

## Overview

Data AI Agent is a ChatGPT-style interface that sits in front of a SQLite database. Users type natural-language questions; the Gemini LLM translates them into SQL, executes the queries, and responds with real numbers, interactive Plotly charts and Mermaid diagrams — all streamed live in the browser.

**Key insight:** The agent never invents numbers. Every statistic it states comes from an actual database query result, making answers trustworthy and auditable. The generated SQL is always shown in a transparent card with Copy and Run buttons so users can verify every query.

**Built for:** Business analysts, product managers, and anyone who needs quick database insights without writing SQL.

---

## Key Features

- **Streaming chat** — Token-by-token streaming responses via Server-Sent Events give an instant, interactive feel. The model starts typing while queries are still running.

- **5 LLM tools** — A hand-crafted tool registry with deterministic JSON schemas exposed to Gemini: `get_schema`, `execute_query`, `generate_chart`, `generate_flowchart`, `explain_data`.

- **SQL transparency** — Every generated SQL query appears in a dedicated card with a **Copy** button and a **▶ Run** button so users can verify, edit and re-execute it themselves.

- **Interactive charts** — Plotly bar, line, pie and scatter charts rendered inline in the chat with dark-theme styling. Charts can be **pinned to a persistent dashboard** that survives page reloads.

- **Mermaid diagrams** — ER diagrams, flowcharts, directed graphs and mindmaps rendered inline via Mermaid.js — great for database structure questions and process-flow requests.

- **Statistical explanations** — The `explain_data` tool computes row counts, min/max/avg/sum and top-N categorical values from any query result, giving the model real numbers to narrate.

- **Schema discovery** — `get_schema` returns every table, column, type, primary key, foreign key and row count. The model consults it automatically before writing SQL for unfamiliar databases.

- **Multi-database support** — Register additional SQLite files in `backend/config.py`; a database selector in the UI lets users switch between them at any time.

- **Query history & favorites** — Questions and generated SQL are saved server-side. Users can star favorites and click any past question to re-ask it instantly.

- **Pinned dashboard** — Any chart can be pinned to a persistent dashboard panel that remains visible across chat sessions and page reloads.

- **Query retry logic** — If a query fails, the model reads the error message, corrects the SQL and retries automatically (up to 2 attempts) before surfacing the failure to the user.

- **Rate-limit handling** — 429 responses from Gemini's free tier are caught; the agent waits the API-recommended delay and retries, streaming a "waiting..." notice to the UI.

- **One-click launcher** — `run.bat` (Windows) / `run.sh` (macOS/Linux) creates the virtual environment, installs dependencies and starts the server in one step.

---

## Screenshots

### 1. Landing — Ready to Ask

The clean dark ChatGPT-style interface on first load with suggested prompts to get started. The left sidebar shows the database selector, chat sessions, query history and pinned dashboard.

### 2. Tabular Answer with SQL Transparency

The agent responds with a clean markdown table. Below the answer, the SQL card shows the exact query used — with Copy and Run buttons for full transparency.

### 3. Multi-Turn Refinement

Follow-up questions work naturally. The agent remembers the last 20 messages and can refine its previous answer ("now filter by last 30 days", "show only the top 3").

### 4. Interactive Bar Chart

Asking "show a bar chart" triggers `execute_query` → `generate_chart` → Plotly figure rendered inline. Dark-themed, fully interactive (hover, zoom, pan). Pin to dashboard with one click.

### 5. ER Diagram

"Draw me the ER diagram for this database" triggers `get_schema` → `generate_flowchart` (type=er) → Mermaid.js renders the entity-relationship diagram inline.

### 6. Pinned Dashboard

Multiple pinned charts arranged in a persistent grid. Each panel shows the chart title, type badge and an unpin button.

---

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Browser (Vanilla JS)              │
│  index.html · style.css · app.js                    │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │
│  │  Chat UI │  │ Dashboard│  │  History / Sidebar │ │
│  └────┬─────┘  └──────────┘  └────────────────────┘ │
└───────┼─────────────────────────────────────────────┘
        │  POST /api/chat  (JSON response with events[])
        │  GET  /api/databases · /api/schema
        │  POST /api/query · GET|POST /api/history
        ▼
┌─────────────────────────────────────────────────────┐
│                FastAPI  (backend/app.py)             │
│  CORS · StaticFiles · Request validation (Pydantic)  │
└───────┬─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│              Streaming Agent  (backend/agent.py)     │
│                                                      │
│  build_contents()  →  Gemini streaming API           │
│       ↑                      ↓                       │
│  function response    function call                  │
│       ↑                      ↓                       │
│  tool_registry.run_tool()  ←─┘                       │
│       │                                              │
│       ├── database_tools.py  (SQL · charts)          │
│       ├── diagram_tools.py   (Mermaid)               │
│       └── explanation_tools.py (stats)               │
└───────┬─────────────────────────────────────────────┘
        │
        ▼
┌──────────────┐    ┌─────────────────┐
│  SQLite DB   │    │  history.json   │
│  grocery.db  │    │  (query store)  │
└──────────────┘    └─────────────────┘
```

**Agent flow:**
```
user message ──▶ Gemini (streaming) ──▶ function call ──▶ tool executes
      ▲                                                        │
      └──────── result fed back to model ◀────────────────────┘
```

The agent loop runs up to `MAX_TOOL_TURNS = 8` iterations, collecting streaming chunks, extracting function calls, dispatching tools, and feeding results back until the model produces a final text-only response.

---

## Agent Tools

| Tool | Purpose | Key Arguments | Returns |
|------|---------|--------------|---------|
| `get_schema` | Discover all tables, columns, PKs, FKs, row counts | `database` | JSON schema dict |
| `execute_query` | Run a read-only SQL SELECT | `sql`, `database` | `{success, columns, data, row_count}` |
| `generate_chart` | Plotly bar / line / pie / scatter chart | `data_json`, `chart_type`, `x_column`, `y_column`, `title` | Plotly figure JSON |
| `generate_flowchart` | Mermaid ER / flowchart / graph / mindmap | `diagram_type`, `title`, `content` | Mermaid source code |
| `explain_data` | Statistical summary: min/max/avg, top categories | `data_json` | `{stats, top_values, explanation}` |

Tool schemas are **explicit JSON declarations** (not auto-generated from Python signatures) for deterministic, SDK-version-independent behavior.

---

## Streaming Protocol

Events are collected server-side and returned as a JSON array `{events: [...]}` from `POST /api/chat`. Each event has a `type` field:

| Event | Payload | Description |
|-------|---------|-------------|
| `delta` | `{text}` | Streaming text chunk from the model |
| `sql` | `{sql}` | Generated SQL (transparency card) |
| `tool` | `{name, args, status}` | Tool call started |
| `tool_result` | `{name, status, summary, ...}` | Tool finished; may include `chart`, `diagram`, `columns`+`rows` |
| `done` | `{text}` | Final assembled assistant message |
| `error` | `{message}` | Failure (shown as red banner in UI) |

---

## Project Structure

```
databsae-ai-agent/
├── frontend/                   Pure HTML/CSS/JS — no build step
│   ├── index.html              Layout + CDN libs (Marked, Plotly, Mermaid)
│   ├── style.css               Dark ChatGPT-like theme (32 KB)
│   └── app.js                  SSE client, artifact renderers, history, dashboard
│
├── backend/                    FastAPI + Gemini agent
│   ├── app.py                  HTTP layer: /api/chat, schema, query, history
│   ├── agent.py                Streaming agent loop (function calling + SSE events)
│   ├── tool_registry.py        5 agent tools + explicit JSON function schemas
│   ├── database_tools.py       get_schema / execute_query / generate_chart
│   ├── diagram_tools.py        generate_diagram (Mermaid, keyword normalization)
│   ├── explanation_tools.py    Statistical summaries (min/max/avg/top-N)
│   ├── history_store.py        JSON-file-backed query history & favorites
│   ├── config.py               Env config + multi-database registry
│   ├── requirements.txt        Python dependencies
│   └── tests/                  pytest unit tests
│       ├── test_database_tools.py
│       └── test_tools.py
│
├── database/
│   ├── grocery_store.db        Sample SQLite e-commerce dataset
│   └── database.py             Schema creation & seed script
│
├── api/
│   └── index.py                Vercel serverless entrypoint
│
├── requirements.txt            Root-level deps (required by Vercel builder)
├── vercel.json                 Vercel build config (includeFiles, routes)
├── run.bat                     One-click launcher — Windows
└── run.sh                      One-click launcher — macOS/Linux
```

---

## Quick Start

### Option A — One-click (recommended)

**Windows:** double-click `run.bat`

**macOS / Linux:**
```bash
chmod +x run.sh
./run.sh
```

The launcher creates the virtual environment, installs dependencies and opens the browser automatically. On the first run it will prompt for your Gemini API key.

### Option B — Manual

```bash
cd backend

# Create virtual environment
py -3.10 -m venv venv          # Windows
python3 -m venv venv           # macOS/Linux

# Activate
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env         # Windows
cp .env.example .env           # macOS/Linux
# Edit .env: set GEMINI_API_KEY=your_key_here

# Start server (from project root)
python -m uvicorn backend.app:app --reload --port 8000
```

Open **http://localhost:8000** and try:

1. *"Top 5 products by revenue — show a bar chart"*
2. *"Now show the revenue trend over time as a line chart"*
3. *"Draw me the ER diagram for this database"*
4. *"Which customers placed the most orders?"*
5. *"Create a flowchart showing how orders flow through our system"*

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | ✅ Yes | — | Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | No | `gemini-3.7-flash` | Gemini model name |

Copy `backend/.env.example` to `backend/.env` and fill in your key.

For Vercel deployments, set these in **Project Settings → Environment Variables**.

---

## API Reference

| Method | Endpoint | Body / Params | Description |
|--------|---------|--------------|-------------|
| `POST` | `/api/chat` | `{messages, database}` | Run agent, returns `{events:[...]}` |
| `GET` | `/api/databases` | — | List registered databases |
| `GET` | `/api/schema` | `?database=grocery` | Full schema for a database |
| `POST` | `/api/query` | `{sql, database}` | Execute raw SQL SELECT |
| `GET` | `/api/history` | `?favorites_only=&database=` | List query history |
| `POST` | `/api/history` | `{question, sql, database}` | Save a history entry |
| `PATCH` | `/api/history/{id}` | `?favorite=true` | Star / unstar an entry |
| `DELETE` | `/api/history/{id}` | — | Delete a history entry |

---

## Running Tests

```bash
cd backend
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS/Linux

python -m pytest tests -v
```

The test suite covers schema discovery, SQL execution safety (non-SELECT rejection), chart generation and tool dispatch.

---

## Deploying to Vercel

1. **Fork / push** this repo to GitHub
2. Import the repo in [vercel.com/new](https://vercel.com/new)
3. Set the environment variable `GEMINI_API_KEY` in **Project Settings → Environment Variables**
4. Deploy — Vercel automatically detects `vercel.json` and builds from `api/index.py`

The `vercel.json` includes `includeFiles` directives that bundle `frontend/`, `database/` and `backend/` into the serverless function.

**Live deployment:** https://aids-nine.vercel.app/

---

## Extending — Add Your Own Database

Register a new SQLite file in `backend/config.py`:

```python
DATABASES = {
    "grocery": { ... },          # existing

    "my_database": {
        "path": r"C:\path\to\my_database.db",
        "description": "Description the agent will use to understand this DB.",
    },
}
```

The database selector in the UI updates automatically. The agent discovers the schema on first query.

---

## Known Limitations

- **Read-only** — Only SQL `SELECT` statements are permitted. No INSERT / UPDATE / DELETE.
- **SQLite only** — The current implementation connects to SQLite files. PostgreSQL / MySQL support would require a connection-string abstraction.
- **History is ephemeral on Vercel** — The JSON history file lives in `/tmp` on serverless deployments and is reset between cold starts. A persistent store (e.g. Vercel KV) would fix this.
- **Chart file saving disabled on Vercel** — Chart HTML files fall back to in-memory JSON only; no HTML is written to disk.
- **Context window** — Only the last 20 messages are sent to the model to stay within token limits.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Google Gemini (`gemini-3.7-flash`) via `google-genai` SDK |
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Data | SQLite, Pandas, NumPy |
| Charts | Plotly Express (server) + Plotly.js (client) |
| Diagrams | Mermaid.js (client-side rendering) |
| Frontend | Vanilla HTML/CSS/JS, Marked.js (markdown) |
| Deployment | Vercel Serverless (`@vercel/python`) |
| Testing | pytest |