---
name: workbench-hint
description: >-
  Reminds the agent to use the sandbox workspace root for file tools and to follow
  the required README plus `agents/` workspace contract.
---

# workbench-hint

Prefer reading and editing files under the active workspace (sandbox cwd). Use `user/`
memory for durable per-user notes when supported. Follow the default contract: root
`README.md`, `agents/`, and `agents/README.md`, with generated agent code under
`agents/<agent-name>/...`. Use bundled skills under `skills/` for Guild authoring workflows.
Fetch official Guild docs before uncommon CLI, non-LLM codegen, integration, trigger, or
custom integration work.
