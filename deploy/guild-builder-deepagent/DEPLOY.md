# Guild builder Deep Agents deploy

This folder is the **Deep Agents CLI** bundle (LangSmith Deployment), generated from the Python workbench via [`../../backend/scripts/export_deepagents_bundle.py`](../../backend/scripts/export_deepagents_bundle.py).

## Regenerate

From the repository root:

```bash
PYTHONPATH=backend/src python3 backend/scripts/export_deepagents_bundle.py
```

## Prerequisites

- `uv tool install deepagents-cli` (or use `uvx deepagents-cli` without installing).
- `LANGSMITH_API_KEY` and Fireworks keys (see `.env.example`): model ID matches the workbench (`openai:accounts/fireworks/models/glm-4p7` in [`config.py`](../../backend/src/agent_workbench/core/config.py)). Set `FIREWORKS_API_KEY`, `OPENAI_BASE_URL=https://api.fireworks.ai/inference/v1`, and `OPENAI_API_KEY` (often the same string as your Fireworks key) like [`agents.py`](../../backend/src/agent_workbench/domain/agents.py) does when `OPENAI_API_KEY` is unset.
- For web search in production, set `TAVILY_API_KEY` and keep `mcp.json` pointed at Tavily’s HTTP MCP URL ([Tavily MCP](https://docs.tavily.com/guides/mcp)).

## Human-in-the-loop

The local workbench’s `request_checkpoint_review` tool is not bundled here. Use [LangSmith human-in-the-loop](https://docs.langchain.com/langsmith/add-human-in-the-loop) or operator review in Studio for architecture / pre-publish / post-publish gates.

## Guild CLI in the sandbox

The workbench runs `guild` on your machine. For deploy parity, use a **custom sandbox image** (or install script) that includes the Guild CLI and whatever auth you use (`guild auth login` flow may need documenting for non-interactive CI).

## Commands

```bash
cd deploy/guild-builder-deepagent
cp .env.example .env   # then fill LANGSMITH_API_KEY, FIREWORKS_API_KEY, OPENAI_* 
```

For Fireworks models, set **`OPENAI_API_KEY`** to the same value as **`FIREWORKS_API_KEY`** (the CLI validates `OPENAI_API_KEY` for `openai:*` models). Match the mapping in [`agents.py`](../../backend/src/agent_workbench/domain/agents.py).

```bash
deepagents dev --port 2024
deepagents deploy --dry-run
deepagents deploy
```

The first `uvx deepagents-cli deploy` can take a while while dependencies resolve; `--dry-run` still performs provider/env validation before bundling.

## Auth and frontend (optional)

If you enable `[frontend].enabled = true`, you must set `[auth]` (Supabase, Clerk, or anonymous) per the [Deep Agents deploy](https://docs.langchain.com/oss/python/deepagents/deploy) docs.
