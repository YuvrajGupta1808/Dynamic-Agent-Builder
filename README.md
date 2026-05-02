# Dynamic Agent Builder

Local Deep Coding Agent Workbench is a localhost-only coding agent UI with a FastAPI backend and a Vite React frontend.

The current workbench is tuned for a Guild-building workflow where the main Deep Agent acts as the orchestrator and delegates specialist work in visible phases instead of one-shotting scaffold, edit, test, and publish in a single blur.

## Safety and Scope Rules

- Workspace-only execution: agents must keep all project artifacts under the active managed workspace (`workspaces/...`).
- No host-temp scaffolding: agents should not create project structures under `/tmp`, `/var`, or other host-absolute roots.
- Relative-path default: file operations and shell commands should target relative workspace paths unless explicitly justified.
- Specialist boundaries:
  - `cli_specialist`, `tester`, `publisher`, `session_specialist`: allowed to run shell commands when required.
  - `validator`: read-only analysis.
  - `decomposer` and `template_selector`: reasoning-first, minimal mutation.
- Ambiguous/fake query handling: if a request is contradictory or unclear, the agent should ask for confirmation before irreversible work.

## Quick Start

First-time setup:

```bash
cp .env.example .env
.venv/bin/python --version >/dev/null 2>&1 || python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e "backend[deepagents,test]"
pnpm install
```

Start the application (backend and frontend together):

```bash
pnpm run dev
```

Open `http://127.0.0.1:5173`. The API is served at `http://127.0.0.1:8000`.

The default model is `mock:deterministic`, so the app runs without provider credentials. Set `WORKBENCH_DEFAULT_MODEL=ollama:devstral-2` or another allowlisted provider model once the matching package and credentials are available.

By default, local agent access is scoped to managed folders under `workspaces/`. Set `WORKBENCH_WORKSPACE_ROOT` and `WORKBENCH_ALLOWED_ROOTS` to the same parent folder if you want managed workspaces somewhere else.

To enable the real Deep Agents path instead of the deterministic mock stream, install the optional backend extras in your Python environment:

```bash
.venv/bin/python -m pip install -e "backend[deepagents,test]"
```

## Orchestrated Guild Builder Flow

The intended operator experience is sequential and reviewable:

1. The supervisor decomposes the requested Guild system and chooses templates with written justification.
2. Shared context and per-agent context are prepared before scaffolding.
3. Only the required Guild folders and files are created.
4. Generated scaffolds are rewritten for the real use case instead of left generic.
5. The agent stops for an architecture checkpoint review before implementation-heavy work continues.
6. Local validation runs before any publish or workspace installation step.
7. The tester -> validator -> editor/sdk repair loop continues until the build is good enough or a real blocker appears.
8. A pre-publish checkpoint review shows exact commands, files, and remaining risks before publish/install can continue.
9. Publish and workspace install happen only after local validation and checkpoint approval.
10. Post-publish live validation records representative inputs and outputs from the installed Guild workspace, then stops for final review.
11. README files and validation/deployment notes are kept current as part of the build, not as an afterthought.

Architecture note: the main Deep Agent is intentionally thin. It now keeps routing and phase-gating guidance, while the specialist subagents own the Guild docs, CLI, SDK, integration, editing, validation, and publishing skills and memories.

Current specialist roster inside the Deep Agent:

- `decomposer`
- `template_selector`
- `agent_initializer`
- `workspace_initializer`
- `context_specialist`
- `cli_specialist`
- `sdk_specialist`
- `integration_specialist`
- `trigger_specialist`
- `session_specialist`
- `documentation_specialist`
- `editor`
- `tester`
- `validator`
- `publisher`

The UI preserves structured run events so you can inspect todo updates, checkpoint approvals, tool calls, specialist activity, validation commands, and the final assistant output from each run.

## Async Subagents

The backend supports synchronous Deep Agents subagents locally today.

Deployment-only async subagents are wired as an optional path because `deepagents` async subagents rely on an Agent Protocol/LangGraph server surface. Set `WORKBENCH_ASYNC_AGENT_SERVER_URL` and matching graph IDs if you want the supervisor to launch background specialists such as:

- `async_tester`
- `async_publisher`
- `async_session_specialist`

Without that remote server surface, the workbench falls back to the synchronous specialist roster above.

## Backend

The backend exposes the planned API surface, normalizes Deep Agents/LangGraph streaming events into app events, and falls back to a deterministic mock coding agent if `deepagents` is not installed.

Notable backend behaviors:

- Workspace files are scoped to managed workspaces under `workspaces/`.
- Guild builder memory and built-in skills are store-backed rather than forced onto disk.
- The default Deep Agents `general-purpose` subagent is disabled in favor of explicit specialists.
- Approval waits no longer show up as stalled runs in the stream.

## Tests

```bash
pnpm test
PYTHONPATH=backend/src .venv/bin/python -m pytest backend/tests
```
