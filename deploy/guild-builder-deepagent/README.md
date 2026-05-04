# Guild builder Deep Agents bundle

LangSmith **Deep Agents Deploy** layout for the same Guild-builder orchestrator and specialists as the local FastAPI workbench.

## Layout

- `deepagents.toml` — agent name and model (defaults to Fireworks `openai:accounts/fireworks/models/glm-4p7`, same family as `WORKBENCH_DEFAULT_MODEL`).
- `AGENTS.md` — main system prompt (regenerated from `agent_workbench.domain.agents`).
- `skills/` — Guild skills + `workbench-seeded-memory` + `workbench-hint` (from export script).
- `subagents/` — one directory per specialist; each has `deepagents.toml`, `AGENTS.md`, and a `skills/` subset.
- `user/AGENTS.md` — per-user memory template (from export script).
- `mcp.json` — HTTP Tavily MCP placeholder ([Tavily MCP docs](https://docs.tavily.com/guides/mcp)); replace the API key in the URL or use your host’s secret injection rules.

## Regenerate from Python sources

```bash
cd /path/to/Dynamic-Agent-Builder
PYTHONPATH=backend/src python3 backend/scripts/export_deepagents_bundle.py
```

Source of truth for the generator is [`backend/scripts/export_deepagents_bundle.py`](../../backend/scripts/export_deepagents_bundle.py).

## Deploy

See [DEPLOY.md](DEPLOY.md).

```bash
cd deploy/guild-builder-deepagent
cp .env.example .env   # then fill in real keys
deepagents dev --port 2024
deepagents deploy --dry-run
deepagents deploy
```
