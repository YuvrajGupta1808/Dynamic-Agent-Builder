## Guild orchestrator workspace memory
This workspace is for building Guild agents with a routing-first Deep Agent workbench.

Default operating rules:
- Start with a concise todo list.
- Keep the main agent focused on routing, phase order, and quality gates.
- Delegate Guild domain work to specialists instead of loading all domain knowledge into the main agent prompt.
- Do not use ad-hoc web search tools for Guild docs, CLI reference, or Guild SDK behavior when a specialist can use the official docs skill instead.
- Triage the request before choosing a workflow:
  1. answer directly when the Guild question is simple and self-contained
  2. route to one narrow specialist when the request is really about CLI syntax, SDK shape, sessions, integrations, or another focused Guild domain
  3. use `decomposer` only when the request requires deciding whether multiple agents or distinct role boundaries are needed
  4. enter the sequential build flow only when real workspace changes, scaffolding, validation, or publish/install work are required
- For common Guild work, the normal flow is:
  1. decide whether decomposition is needed
  2. if needed, decide how many agents are needed
  3. choose the Guild template and justify it
  4. create or select the remote Guild workspace
  5. create the local `agents/<agent-name>/` directory before any agent init
  6. initialize only the required local agent repos under `agents/<agent-name>/...`
  7. adapt generated files to the real use case under `agents/<agent-name>/...`
  8. run focused local validation
  9. repair the smallest failure and rerun narrowly
  10. publish/install only after local validation is good enough
  11. run representative live validation and summarize the exact inputs/outputs
- Default local workspace contract: root `README.md`, `agents/`, and `agents/README.md`.
- Track three identifiers explicitly: local builder workspace root, local agent repo under `agents/<agent-name>/`, and selected remote Guild workspace.
- Workspace-local `skills/` autoloading is disabled unless explicitly enabled by configuration.
