# Dynamic Agent Builder

Local Deep Coding Agent Workbench is a localhost-only coding agent UI with a FastAPI backend and a Vite React frontend.

## Quick Start

```bash
cp .env.example .env
.venv/bin/python --version >/dev/null 2>&1 || python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e "backend[deepagents,test]"
pnpm install
pnpm dev
```

Open `http://127.0.0.1:5173`. The backend listens on `http://127.0.0.1:8787`.

The default model is `mock:deterministic`, so the app runs without provider credentials. Set `WORKBENCH_DEFAULT_MODEL=ollama:devstral-2` or another allowlisted provider model once the matching package and credentials are available.

By default, local agent access is scoped to managed folders under `workspaces/`. Set `WORKBENCH_WORKSPACE_ROOT` and `WORKBENCH_ALLOWED_ROOTS` to the same parent folder if you want managed workspaces somewhere else.

To enable the real Deep Agents path instead of the deterministic mock stream, install the optional backend extras in your Python environment:

```bash
cd backend
python3 -m pip install ".[deepagents]"
```

## Backend

```bash
PYTHONPATH=backend/src .venv/bin/python -m uvicorn agent_workbench.main:app --host 127.0.0.1 --port 8787 --reload
```

The backend exposes the planned API surface, normalizes Deep Agents/LangGraph streaming events into app events, and falls back to a deterministic mock coding agent if `deepagents` is not installed.

## Tests

```bash
pnpm test
```
