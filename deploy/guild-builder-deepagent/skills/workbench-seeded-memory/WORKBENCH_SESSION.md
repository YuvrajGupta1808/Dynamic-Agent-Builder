## Session memory
Use this file for preferences and durable facts for this conversation session.
You may update it when the user asks you to remember something.

When working in a Guild builder workspace:
- Treat the main Deep Agent as an orchestrator, not the holder of all Guild implementation knowledge
- Delegate Guild docs, CLI, SDK, integration, testing, editing, and publish details to the relevant specialist subagents
- Default local workspace contract: root `README.md`, `agents/`, and `agents/README.md`
- Keep generated agent code under `agents/<agent-name>/...`
- Avoid top-level side artifacts unless the user explicitly asks for them
- Keep the active workspace `README.md` and `agents/README.md` current
- Do not update repository root/global `README.md` unless explicitly requested by the user in the current run
- Use explicit confirmation when the request is fake, contradictory, or would create unnecessary artifacts
