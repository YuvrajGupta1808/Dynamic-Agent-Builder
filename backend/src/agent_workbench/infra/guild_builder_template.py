"""Built-in Guild builder skill content for virtual store seeding."""

from __future__ import annotations


SKILL_FILES: dict[str, str] = {
    "skills/guild-orchestrator-routing/SKILL.md": """---
name: guild-orchestrator-routing
description: Use this skill only for the main Deep Agent orchestrator. It defines which specialist subagent should handle each Guild-building concern, when to fan out work in parallel, and the phase gates that must be satisfied before publish.
allowed-tools: read_file, write_todos
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-orchestrator-routing

## Overview

This skill is for the supervisor only. It should not carry detailed Guild CLI,
SDK, integration, or publish knowledge. Its job is to route work to the right
specialist and keep the build sequential and reviewable.

## Supporting files

- `routing-map.md` maps user intents and build phases to specialist subagents

## Instructions

1. Read `routing-map.md`.
2. Maintain a clear phase order: understand request -> decompose -> choose templates -> CLI initialize -> edit agent code -> local validate -> repair loop -> publish/install -> live validate.
3. Delegate domain work to specialists instead of holding Guild details in the main prompt.
4. When two specialist tasks are independent, launch them in parallel in the same turn.
5. Stop for `request_checkpoint_review` at architecture, pre-publish, and post-publish boundaries instead of one-shotting the whole workflow.
6. Do not let publish start before tester/validator work says local validation is good enough and the pre-publish checkpoint is approved.
7. Use `documentation_specialist` only for an explicit workspace `README.md` need.
""",
    "skills/guild-orchestrator-routing/routing-map.md": """# Orchestrator Routing Map

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
""",
    "skills/guild-official-docs/SKILL.md": """---
name: guild-official-docs
description: Use this skill for any Guild AI implementation task that depends on exact CLI behavior, SDK/runtime details, integrations, triggers, workspace context publishing, versioning, or other details that may differ by topic. Fetch the official Guild docs index first, choose only the relevant pages, then read those pages before deciding commands or code.
allowed-tools: execute, read_file, write_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-official-docs

## Overview

This skill retrieves current Guild documentation from the official docs site.
Use it whenever precise Guild behavior matters more than heuristics.

## Supporting files

- `fetch-checklist.md` explains how to fetch and narrow the official docs
- `topic-map.md` maps common tasks to likely official documentation pages

## Instructions

1. Read `fetch-checklist.md`.
2. Fetch the official index at `https://docs.guild.ai/llms.txt`.
3. Choose only the relevant pages for the current task.
4. Fetch those pages before deciding commands or code.
5. Summarize the rules you will rely on before executing the Guild workflow.
6. Only materialize docs into the workspace if a long-running task would benefit from a local reference file.
7. Do not use `quick_search` or generic web search for Guild docs retrieval. Start from the official docs URLs directly.
""",
    "skills/guild-official-docs/fetch-checklist.md": """# Official Docs Fetch Checklist

## Fetch method

Use the shell via `execute` to fetch the Guild docs because the official docs are not stored locally by default.
Do not use `quick_search` or broad web search for Guild docs discovery.

Examples:
- `curl -fsSL https://docs.guild.ai/llms.txt`
- `curl -fsSL https://docs.guild.ai/cli/commands.md`

## Always fetch docs before

- running uncommon Guild CLI commands
- generating non-LLM Guild agent code
- integration work
- workspace context publishing
- trigger creation or update
- custom integration design
- troubleshooting CLI/auth/versioning edge cases

## Selection rule

- Start with the index
- Pick only the 2-4 most relevant pages
- Prefer specific reference/how-to pages over broad overviews

## Materialization rule

- Do not mirror the docs into the workspace by default
- Create a local reference note only if the task is long-running or the same rules will be reused repeatedly
""",
    "skills/guild-official-docs/topic-map.md": """# Guild Docs Topic Map

- CLI commands: `https://docs.guild.ai/cli/commands.md`
- CLI workflow/setup: `https://docs.guild.ai/cli/getting-started.md`
- LLM agents: `https://docs.guild.ai/guide/llm-agents.md`
- Auto-managed state agents: `https://docs.guild.ai/guide/coded-agents.md`
- Self-managed state agents: `https://docs.guild.ai/guide/self-managed-agents.md`
- State model: `https://docs.guild.ai/guide/state.md`
- Tasks/runtime: `https://docs.guild.ai/guide/tasks.md`
- Versions/publish: `https://docs.guild.ai/guide/versions.md`
- Workspace context: `https://docs.guild.ai/platform/context.md`
- Workspaces: `https://docs.guild.ai/platform/workspaces.md`
- Sessions: `https://docs.guild.ai/platform/sessions.md`
- Triggers: `https://docs.guild.ai/platform/triggers.md`
- Integrations: `https://docs.guild.ai/platform/integrations.md`
- Credentials: `https://docs.guild.ai/platform/credentials.md`
- SDK intro: `https://docs.guild.ai/guide/sdk-introduction.md`
- Task object: `https://docs.guild.ai/sdk/task-object.md`
- Tool sets: `https://docs.guild.ai/sdk/tools.md`
- Custom integrations: `https://docs.guild.ai/services/create-an-integration.md`
""",
    "skills/guild-sdk-llm-agent/SKILL.md": """---
name: guild-sdk-llm-agent
description: Use this skill when generating or reviewing a Guild LLM agent. It covers llmAgent structure, tool set guidance, and when to refresh from official docs before finalizing code.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-sdk-llm-agent

## Overview

This skill helps build prompt-driven Guild agents with `llmAgent`.

## Supporting files

- `implementation-checklist.md` contains the LLM-agent authoring checklist

## Instructions

1. Read `implementation-checklist.md`.
2. If the task depends on exact Guild SDK behavior, fetch the official docs using `guild-official-docs` first.
3. Keep the tool set minimal.
4. Prefer role clarity, prompt quality, and explicit handoff rules.
""",
    "skills/guild-sdk-llm-agent/implementation-checklist.md": """# LLM Agent Checklist

- Confirm the job is primarily prompt + tools
- Use `llmAgent`
- Keep tools minimal
- Add `guildTools` only if Guild platform operations are needed
- Use multi-turn only when the interaction should stay open
- Prefer clear routing/refusal rules over sprawling prompts
""",
    "skills/guild-sdk-auto-managed/SKILL.md": """---
name: guild-sdk-auto-managed
description: Use this skill when generating or reviewing a Guild AUTO_MANAGED_STATE agent. It covers the procedural async run model, schema structure, and when to fetch official docs before writing non-LLM code.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-sdk-auto-managed

## Overview

This skill helps build procedural Guild agents using the auto-managed state
model.

## Supporting files

- `implementation-checklist.md` contains the auto-managed authoring checklist

## Instructions

1. Read `implementation-checklist.md`.
2. Always fetch official Guild docs before generating non-LLM agent code.
3. Verify that the workflow is sequential and does not need parallel tool rounds.
4. Record why auto-managed state fits better than LLM or BLANK.
""",
    "skills/guild-sdk-auto-managed/implementation-checklist.md": """# Auto-Managed State Checklist

- Confirm the task is sequential and typed
- Use `"use agent"` when required by the template/runtime pattern
- Define input/output schemas clearly
- Avoid Promise.all / Promise.any / Promise.race style parallel control flow
- Prefer this model only when explicit procedural logic is needed
""",
    "skills/guild-sdk-self-managed/SKILL.md": """---
name: guild-sdk-self-managed
description: Use this skill when generating or reviewing a Guild self-managed agent from the BLANK template. It covers explicit state, start/onToolResults flow, and when to fetch official docs before implementing advanced orchestration.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-sdk-self-managed

## Overview

This skill helps build explicit state-machine Guild agents.

## Supporting files

- `implementation-checklist.md` contains the self-managed authoring checklist

## Instructions

1. Read `implementation-checklist.md`.
2. Always fetch official Guild docs before implementing self-managed state logic.
3. Use this only when explicit lifecycle control or parallel tool calls are truly required.
4. Record the state model and transition reasoning in the agent docs.
""",
    "skills/guild-sdk-self-managed/implementation-checklist.md": """# Self-Managed State Checklist

- Confirm that explicit lifecycle/state control is required
- Define input/output/state schemas clearly
- Implement `start` and `onToolResults`
- Use save/restore deliberately
- Keep transitions readable and documented
- Prefer this model only when simpler options do not fit
""",
    "skills/guild-workspace-context/SKILL.md": """---
name: guild-workspace-context
description: Use this skill when writing, publishing, or reviewing Guild workspace context. It covers what belongs in shared context, when to fetch official docs, and how to avoid bloated context files.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-workspace-context

## Overview

This skill helps write concise shared Guild workspace context.

## Supporting files

- `context-checklist.md` contains scope and publishing guidance

## Instructions

1. Read `context-checklist.md`.
2. Fetch official Guild docs before running workspace context publish flows.
3. Keep only cross-agent facts in shared workspace context.
4. Put role-specific guidance in per-agent files, not shared context.
""",
    "skills/guild-workspace-context/context-checklist.md": """# Workspace Context Checklist

- Include only cross-agent facts
- Keep shared tone, policy, and definitions here
- Exclude role-specific prompts and implementation notes
- Refresh official docs before using `guild workspace context ...` commands
- Materialize local reference notes only when helpful for a long-running task
""",
    "skills/guild-triggers/SKILL.md": """---
name: guild-triggers
description: Use this skill when planning or creating Guild triggers. It covers webhook/time trigger flows and requires refreshing from official docs before using trigger commands.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-triggers

## Overview

This skill helps plan and create Guild triggers.

## Supporting files

- `trigger-checklist.md` contains trigger decision and command guidance

## Instructions

1. Read `trigger-checklist.md`.
2. Always fetch official Guild docs before creating or updating triggers.
3. Confirm whether the task truly needs webhook or time automation.
4. Record the trigger assumptions in project docs before running commands.
""",
    "skills/guild-triggers/trigger-checklist.md": """# Trigger Checklist

- Determine whether the trigger is time-based or webhook-based
- Confirm the target agent and required input shape
- Refresh docs before `guild trigger create` or `guild trigger update`
- Record service/event/action assumptions for webhook triggers
- Keep trigger creation out of the flow unless the user actually needs automation
""",
    "skills/guild-integrations/SKILL.md": """---
name: guild-integrations
description: Use this skill when choosing or wiring Guild first-party integrations. It covers credentials, tool-selection boundaries, and when to refresh the official integrations docs before implementation.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-integrations

## Overview

This skill helps work with Guild's first-party integrations.

## Supporting files

- `integration-checklist.md` contains integration-selection guidance

## Instructions

1. Read `integration-checklist.md`.
2. Always fetch official Guild docs before integration work.
3. Choose only the specific integration pages needed for the task.
4. Keep integration instructions scoped to the agents that need them.
""",
    "skills/guild-integrations/integration-checklist.md": """# Integration Checklist

- Identify whether a first-party integration already exists
- Refresh official docs before selecting tool packages or commands
- Document credential requirements and failure cases
- Keep integration guidance role-specific
- Avoid broad tool exposure when a narrow subset is enough
""",
    "skills/guild-custom-integrations/SKILL.md": """---
name: guild-custom-integrations
description: Use this skill when designing a custom Guild integration for a service that is not covered by a first-party integration. It requires reading the official custom integration docs before proposing schemas, auth, endpoints, or webhook behavior.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-custom-integrations

## Overview

This skill helps design custom Guild integrations.

## Supporting files

- `custom-integration-checklist.md` contains design steps and safety checks

## Instructions

1. Read `custom-integration-checklist.md`.
2. Always fetch official Guild docs before custom integration design.
3. Confirm that a first-party integration is not sufficient.
4. Document auth, endpoints, webhook expectations, and versioning assumptions before generating implementation artifacts.
""",
    "skills/guild-custom-integrations/custom-integration-checklist.md": """# Custom Integration Checklist

- Confirm first-party integrations are insufficient
- Refresh the official Create an Integration docs first
- Record auth type, endpoint mapping, and webhook assumptions
- Keep versioning and publish behavior explicit
- Do not invent custom integration behavior from memory
""",
    "skills/guild-publish-and-versions/SKILL.md": """---
name: guild-publish-and-versions
description: Use this skill when saving, validating, publishing, or reviewing Guild agent versions. It covers save/publish/version flows and requires refreshing official docs before final publish decisions.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-publish-and-versions

## Overview

This skill handles Guild save, validate, publish, and version management work.

## Supporting files

- `publish-checklist.md` contains the publish/version checklist

## Instructions

1. Read `publish-checklist.md`.
2. Refresh the official docs before save/publish/versioning work when exact behavior matters.
3. Separate local validation from publish decisions.
4. Record publish outcomes and version assumptions in project docs.
5. Keep post-publish validation evidence focused on representative input/output behavior.
""",
    "skills/guild-publish-and-versions/publish-checklist.md": """# Publish and Versions Checklist

- Validate locally before publish
- Refresh official docs before version-sensitive commands
- Record save/publish outcomes and failure cases
- Keep version assumptions explicit
- Avoid guessing publish behavior from memory
- Capture representative post-publish input/output examples when the user asks for live validation evidence
""",
    "skills/guild-cli-troubleshooting/SKILL.md": """---
name: guild-cli-troubleshooting
description: Use this skill when Guild CLI commands fail because of auth, workspace selection, validation, or environment setup issues. It requires refreshing official docs before relying on uncommon troubleshooting flows.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-cli-troubleshooting

## Overview

This skill helps diagnose Guild CLI failures.

## Supporting files

- `troubleshooting-checklist.md` contains a failure triage checklist

## Instructions

1. Read `troubleshooting-checklist.md`.
2. Capture the exact failing command and its stderr/stdout.
3. Refresh official docs before relying on uncommon remediation paths.
4. Patch the smallest relevant file or environment assumption before retrying.
""",
    "skills/guild-cli-troubleshooting/troubleshooting-checklist.md": """# CLI Troubleshooting Checklist

- Capture the exact failing command
- Distinguish auth, workspace selection, validation, and environment failures
- Refresh official docs before uncommon or risky remediation steps
- Retry the narrowest command possible
- Document the failure and fix in local notes if the task is long-running
""",
    "skills/guild-agent-decomposition/SKILL.md": """---
name: guild-agent-decomposition
description: Use this skill when a request needs to be decomposed into multiple Guild agents with distinct roles, boundaries, and ownership. It helps prevent unnecessary agent sprawl and should escalate to official docs only if the decomposition depends on exact Guild behavior.
allowed-tools: read_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-agent-decomposition

## Overview

This skill helps decide how many Guild agents a workspace actually needs and
what each agent should own.

## Supporting files

- `decision-checklist.md` contains decomposition rules and anti-patterns

## Instructions

1. Read `decision-checklist.md`.
2. Return the minimum viable agent set directly from the user request.
3. Assign each agent one clear role and boundary.
4. Avoid creating an extra orchestrator agent unless explicitly required.
5. If the decomposition depends on exact Guild runtime behavior, use `guild-official-docs` first.
""",
    "skills/guild-agent-decomposition/decision-checklist.md": """# Decomposition Checklist

- Prefer 1 agent when one role can answer the whole request cleanly
- Prefer 2-4 agents when responsibilities are materially different
- Split by role boundary, not by implementation whim
- Reject unnecessary orchestration agents when Guild workspace already provides coordination
""",
    "skills/guild-template-selection/SKILL.md": """---
name: guild-template-selection
description: Use this skill when deciding which Guild agent template to use. It maps requested behavior to LLM, AUTO_MANAGED_STATE, or BLANK with a written justification in chat, and it should refresh official docs before non-LLM agent generation.
allowed-tools: read_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-template-selection

## Overview

This skill selects the right Guild template by capability analysis rather than
habit.

## Supporting files

- `selection-matrix.md` contains the template decision matrix

## Instructions

1. Read `selection-matrix.md`.
2. Identify whether the job is prompt-driven, sequential, or explicitly stateful.
3. If the likely answer is not `LLM`, fetch official Guild docs first.
4. Return the chosen template and reasoning in the response.
5. Record rejected alternatives briefly.
""",
    "skills/guild-template-selection/selection-matrix.md": """# Template Selection Matrix

## Use `LLM`
- conversational or prompt-driven
- tool choice matters more than deterministic control flow

## Use `AUTO_MANAGED_STATE`
- procedural and sequential
- typed schemas and resumability matter
- no parallel tool rounds

## Use `BLANK`
- explicit lifecycle/state control needed
- parallel tool calls matter
- auto-managed compiler constraints are a bad fit
""",
    "skills/guild-context-writer/SKILL.md": """---
name: guild-context-writer
description: Use this skill only when explicit context placement work is required. It compresses noisy documentation into high-signal authored context and should refresh official docs before workspace context publishing.
allowed-tools: read_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-context-writer

## Overview

This skill applies Deep Agents context-engineering rules to Guild workspace
projects.

## Supporting files

- `context-checklist.md` contains placement rules for memory, skills, shared context, and agent-specific context

## Instructions

1. Read `context-checklist.md`.
2. Under the default contract, prefer no extra workspace artifacts.
3. Put role-specific guidance in the agent folder only when explicitly needed.
4. Fetch official docs before running workspace context publish commands.
5. Update the workspace `README.md` only when the user explicitly wants operator-facing docs.
""",
    "skills/guild-context-writer/context-checklist.md": """# Context Checklist

- Prefer no extra context files under the default contract
- Per-agent context should describe scope, refusals, and examples
- Workspace-local `skills/` are opt-in only
- Long outputs and logs should stay in files, not chat history
- Workspace `README.md` should describe the current orchestrator flow when it exists
""",
    "skills/guild-cli-runbook/SKILL.md": """---
name: guild-cli-runbook
description: Use this skill when running or planning Guild CLI commands for agent scaffolding, testing, publishing, workspace installation, and chat validation. It should escalate to official docs before uncommon commands or exact CLI edge cases.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-cli-runbook

## Overview

This skill provides the command flow for local Guild agent project work and
workspace-level Guild operations.

## Supporting files

- `commands.md` lists common per-agent and workspace-level commands

## Instructions

1. Read `commands.md`.
2. Run agent-folder commands from the correct agent directory.
3. Run workspace commands only after agents validate locally.
4. Do not create side-artifact reports by default.
5. Fetch official docs before uncommon Guild commands or when exact CLI behavior matters.
6. Do not run repeated `guild --help` commands for common flows already covered by workspace memory or this runbook.
""",
    "skills/guild-cli-runbook/commands.md": """# Guild CLI Commands

## Agent folder
- `guild auth status`
- `guild agent init`
- `guild agent test --ephemeral`
- `guild agent chat`
- `guild agent save`

## Workspace
- `guild workspace list`
- `guild workspace create <workspace-name>`
- `guild workspace select <workspace-id-or-name>`
- `guild workspace agent add <identifier>`
- `guild workspace agent list`
- `guild chat --agent <identifier> --workspace <workspace-id>`
- `guild session list --workspace <workspace-id>`
""",
    "skills/guild-repair-loop/SKILL.md": """---
name: guild-repair-loop
description: Use this skill when a Guild CLI validation, test, publish, or workspace command fails. It helps identify the smallest file change to make before rerunning the next command and should refresh official docs before uncommon remediation steps.
allowed-tools: execute, read_file, edit_file, write_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-repair-loop

## Overview

This skill keeps the Deep Agent in a tight diagnose-patch-rerun loop.

## Supporting files

- `failure-playbook.md` contains the repair-loop checklist

## Instructions

1. Read `failure-playbook.md`.
2. Capture stdout/stderr first.
3. Identify whether the issue is in prompt, context, code, or workspace setup.
4. Patch the smallest relevant file.
5. Refresh official docs before relying on uncommon remediation paths.
6. Rerun only the necessary command.
7. Keep validation output in chat unless the user explicitly asks for a file.
""",
    "skills/guild-repair-loop/failure-playbook.md": """# Failure Playbook

1. Capture the failed command exactly
2. Summarize the failure in chat unless the user explicitly asked for a file
3. Identify the smallest relevant file to change
4. Patch that file
5. Rerun the narrowest command that proves the fix
6. Keep validation notes concise and operator-readable
""",
    "skills/guild-workspace-publisher/SKILL.md": """---
name: guild-workspace-publisher
description: Use this skill when published Guild agents need to be installed into a Guild workspace, shared context must be published, or live workspace chats need to be validated. It should refresh official docs before workspace publishing or trigger flows.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-workspace-publisher

## Overview

This skill handles the Guild workspace steps after local agent validation.

## Supporting files

- `workspace-checklist.md` contains the installation and validation checklist

## Instructions

1. Read `workspace-checklist.md`.
2. Create or select the Guild workspace.
3. Install validated agents.
4. Fetch official docs before shared context publish or trigger work.
5. Publish shared workspace context if required.
6. Run representative chats and record outcomes.
7. When the user wants evidence, keep the post-publish notes focused on representative input/output behavior.
""",
    "skills/guild-workspace-publisher/workspace-checklist.md": """# Workspace Checklist

- Confirm the target workspace exists or create it
- Select the workspace explicitly
- Install each published agent
- Verify installed agents with `guild workspace agent list`
- Publish shared workspace context when needed
- Run representative chats and inspect resulting sessions
- Summarize representative prompt/response behavior when the task needs an audit trail
""",
}
