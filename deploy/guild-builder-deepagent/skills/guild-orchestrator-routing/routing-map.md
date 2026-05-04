# Orchestrator Routing Map

## Main-agent responsibility

- understand the user's goal
- decide the current phase
- choose which specialist should work next
- gate publish behind local validation
- stop for checkpoint review before moving into publish or finalization
- keep the overall run legible for the user

## Specialist routing

- system decomposition -> `decomposer`
- template choice -> `template_selector`
- per-agent scaffold init -> `agent_initializer`
- workspace creation/selection/bootstrap -> `workspace_initializer`
- explicit context placement -> `context_specialist`
- exact Guild CLI commands or flags -> `cli_specialist`
- Guild SDK code shape or non-LLM logic -> `sdk_specialist`
- integrations and credentials -> `integration_specialist`
- triggers and automation wiring -> `trigger_specialist`
- scaffold rewriting and use-case-specific edits -> `editor`
- local validation execution -> `tester`
- failure diagnosis and smallest-next-fix guidance -> `validator`
- workspace README updates -> `documentation_specialist`
- workspace install, publish, and live validation -> `publisher`
- representative live session evaluation -> `session_specialist`

## Parallel fan-out examples

- `decomposer` then `template_selector` per role
- `tester` and `documentation_specialist` only when a workspace README update is already justified

## Guardrails

- The main agent should not fetch Guild docs itself when a specialist can do it.
- The main agent should not hold Guild CLI or SDK specifics as always-loaded memory.
- The main agent should summarize specialist outputs and decide the next delegation step.
