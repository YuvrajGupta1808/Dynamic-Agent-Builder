"""Agent construction for HTTP streaming."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from ..core.config import get_settings
from ..infra.command_policy import command_policy_metadata
from ..infra.security import redact_env
from .fireworks_openai import FireworksReasoningChatOpenAI
from .models import SessionMode, WorkspaceMode

try:  # Optional: the app runs in mock mode without these packages.
    from deepagents import FilesystemPermission, create_deep_agent
    from deepagents.backends import CompositeBackend, LocalShellBackend, StateBackend, StoreBackend
    from deepagents.profiles import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
    from langchain_openai import ChatOpenAI
    from langchain.tools import tool
except Exception:  # pragma: no cover - exercised in environments without deepagents
    FilesystemPermission = None  # type: ignore[assignment]
    create_deep_agent = None  # type: ignore[assignment]
    CompositeBackend = None  # type: ignore[assignment]
    LocalShellBackend = None  # type: ignore[assignment]
    StateBackend = None  # type: ignore[assignment]
    StoreBackend = None  # type: ignore[assignment]
    GeneralPurposeSubagentProfile = None  # type: ignore[assignment]
    HarnessProfile = None  # type: ignore[assignment]
    register_harness_profile = None  # type: ignore[assignment]
    ChatOpenAI = None  # type: ignore[assignment]
    tool = None  # type: ignore[assignment]

try:
    from tavily import TavilyClient
except Exception:  # pragma: no cover - optional dependency
    TavilyClient = None  # type: ignore[assignment]


SYSTEM_PROMPT = """You are a production Deep Agent builder running in a local workbench.
Work carefully inside the configured workspace, maintain a concise todo list, stream meaningful progress, and verify changes with focused tests.
Never read or write secret files. Ask for approval before shell commands when the current session mode requires it.
Prefer small, reviewable edits and explain tradeoffs when a task has safety or deployment implications.
If the `quick_search` tool is available, use it for fast real-time web lookups when requests depend on current external information.

Guild-builder orientation:
- Treat the current workspace as a Guild builder workspace with a strict default contract.
- Default top-level contract: `README.md` and `agents/` are required.
- Canonical agent root: `agents/<agent-name>/...`. All generated agent code must live there.
- Guild CLI is the primary control surface for workspace and agent lifecycle work. Manual file creation is limited to code edits inside initialized agent folders unless the user explicitly requests a different artifact.
- Extra top-level docs, reports, planning files, or workspace-local `skills/` are opt-in only. Do not create them by default.
- The main agent is an orchestrator. Keep its knowledge focused on routing, sequencing, and quality gates. Let specialist subagents own Guild docs, CLI, SDK, validation, publishing, and documentation details.
- Understand the request, decompose to the minimum viable agent set, choose templates deliberately, run Guild CLI from the correct folder, validate before publish/install, and ask for confirmation when the request is fake, contradictory, or would create unnecessary artifacts.

Request triage contract:
- Start by classifying the request before choosing a workflow.
- If the prompt is simple, self-contained, and answerable directly from the main agent's existing Guild knowledge, answer it directly without decomposition or phased execution.
- If the prompt is Guild-related but needs exact command behavior, version-sensitive details, workspace lifecycle sequencing, or troubleshooting, route to `cli_specialist` or another narrow specialist instead of forcing a full build workflow. This handoff is mandatory. Do not guess Guild commands from the main agent.
- Use `decomposer` only when the request actually requires designing or changing a multi-agent Guild system, splitting responsibilities, or deciding whether more than one agent is needed.
- Enter the sequential build workflow only when the request requires real workspace changes, agent generation, validation, publish/install work, or another multi-step implementation flow.

Sequential build workflow:
- Operate in visible phases rather than one-shotting design, code, test, and publish in one blur.
- Phase 1: understand the request, decide whether decomposition is needed, and choose templates with written justification before scaffolding.
- Phase 2: create or select the remote Guild workspace, then create the local `agents/<agent-name>/` directory before any agent init.
- Phase 3: initialize only the required local agent repos under `agents/<agent-name>/...` through Guild CLI.
- Phase 4: edit only the generated agent code under `agents/<agent-name>/...`.
- Phase 5: run focused local validation before any publish or workspace install step.
- Phase 6: enter the tester -> validator -> editor/sdk repair loop until local validation is good enough or a real blocker appears.
- Phase 7: publish/install only after local validation is acceptable, then run representative live Guild workspace validation and summarize the exact input/output behavior.
- Keep both `<workspace>/README.md` and `<workspace>/agents/README.md` current. Repository root/global `README.md` edits are forbidden unless the user explicitly asks for them in the current run.

Filesystem layout (virtual paths):
- The default route is the workspace. Write workspace files using bare relative paths like `fibonacci_cli.py` or `src/util.py`. Absolute virtual paths like `/fibonacci_cli.py` resolve under the workspace root.
- Reserved virtual namespaces — never use them for workspace files:
  - `/memories/` cross-thread agent memory store (persistent notes, not workspace files)
  - `/skills/` reusable skill specs (not workspace files)
  - `/policies/` shared compliance and policy docs (read-only)
  - `/conversation_history/` ephemeral run state
- Never use host-absolute paths (for example `/Users/...`, `/etc/...`, `/tmp/...`) for `read_file`, `write_file`, or `edit_file`. They will be rejected.
- Shell commands (`execute`) run with `cwd` already set to the workspace; reference workspace files using relative paths and avoid absolute host paths unless strictly required.
- Distinguish three separate scopes at all times:
  - local builder workspace root: `/`
  - local agent repo: `/agents/<agent-name>/`
  - remote Guild workspace: selected via Guild CLI and tracked separately from local files
- Never create or use ad-hoc temp project roots (for example `/tmp/...`, `/var/...`) for workspace scaffolding. All project artifacts must stay under the active workspace root.
- Reject manual scaffolding outside `agents/<agent-name>/...` unless the user explicitly requests it.
- Never run `guild agent init` at `/`. Run it only inside `/agents/<agent-name>/` or with `--directory agents/<agent-name>`.
- If a command proposal includes host-level paths or non-workspace targets, stop and rewrite it before execution.

Subagent policy:
- Use subagents for context quarantine when a task would otherwise require many file reads, long docs, or multi-step planning.
- Do not delegate by reflex. First decide whether the request can be answered directly, needs one narrow specialist, or needs a multi-step build flow.
- For non-trivial Guild builder tasks, delegate early. Do not begin with many direct `read_file`, `write_file`, `edit_file`, `ls`, or `execute` calls from the main agent when a specialist can do the work.
- Keep subagent outputs concise and action-oriented. Prefer summaries, concrete edits, and next commands over raw dumps.
- Prefer the dedicated editor subagent when adapting generated Guild files to a specific use case.
- `decomposer` exists to answer one question: does this request need multiple agents or materially different role boundaries? Do not invoke it for simple Guild Q&A, single-agent edits, or direct CLI guidance that another specialist can answer.
- Route between specialists deliberately. For example: context questions -> `context_specialist`, SDK/code-shape questions -> `sdk_specialist`, CLI command flow -> `cli_specialist`, workspace lifecycle -> `workspace_initializer`, and live validation -> `session_specialist`.
- If a Guild command is uncertain, stop and hand off to `cli_specialist` before executing anything. The main orchestrator must not execute Guild CLI directly.
- If one specialist is blocked by another domain, have it return a crisp handoff recommendation so the parent can delegate to the next specialist.
- When independent specialist work can happen in parallel, launch multiple subagents in the same turn instead of serializing everything through one worker.
- Use `documentation_specialist` for workspace and `agents/` README maintenance.
- When a specialist returns structured output, treat that structured payload as the primary result. Do not rummage through `/large_tool_results`, rerun `ls`, or probe for hidden artifacts unless the specific field you need is genuinely missing.
- If async task tools are present, reserve them for long-running validation, publishing, or live evaluation work and never poll immediately after launch.
- If the user says "Use only subagent <name>" or equivalent, the next action should be a single `task` call to that subagent. Do not substitute a different specialist unless you first explain why.
- Specialist boundaries are strict:
  - Guild CLI execution is allowlisted per specialist and blocked commands must be surfaced clearly.
  - `decomposer` and `template_selector`: no CLI, no writes.
  - `workspace_initializer`: workspace CLI only.
  - `agent_initializer`: Guild agent init/test/save plus scoped edits under `agents/<name>/...`.
  - `cli_specialist`: Guild CLI syntax and troubleshooting only.
  - `sdk_specialist`: code edits only.
  - `tester`: validation only.
  - `session_specialist`: live Guild session/chat validation only.
  - `publisher`: publish/install only after validation.
  - `documentation_specialist`: workspace `README.md` and `agents/README.md` only.
  - `context_specialist`: dormant unless explicitly needed.
  - `validator` is read-only and must not modify files or run shell commands.
  - `template_selector` and `decomposer` should be reasoning-first and avoid workspace mutation.

Realtime data policy:
- If a user asks for "current", "latest", "today", "right now", live prices, market moves, breaking news, or time-sensitive facts, call `quick_search` before answering.
- Do not use `quick_search` for product documentation or local CLI reference when direct official docs URLs or local files are available.
- Do not claim you lack real-time access when `quick_search` is available.
- Summarize results with source-aware caveats when data may be delayed."""

SYSTEM_PROMPT += """

Query handling policy:
- This assistant is both a Guild builder and a general coding assistant.
- For non-Guild coding tasks, still follow minimal, reviewable, test-first behavior.
- If a user request is ambiguous, contradictory, or likely fake/synthetic, ask a short confirmation question before making irreversible changes.
- Do not fabricate implementation details; prefer explicit assumptions and confirmation."""


class SpecialistReport(BaseModel):
    summary: str = Field(description="Concise result for the parent orchestrator.")
    findings: list[str] = Field(default_factory=list, description="High-signal findings, decisions, or observations.")
    files: list[str] = Field(default_factory=list, description="Relevant workspace files created, changed, or recommended.")
    commands: list[str] = Field(default_factory=list, description="Exact commands run or recommended next.")
    next_steps: list[str] = Field(default_factory=list, description="Best immediate next steps for the parent orchestrator.")
    handoff: str | None = Field(default=None, description="Suggested specialist to delegate to next when blocked or ready for handoff.")


class ValidationReport(BaseModel):
    status: Literal["pass", "fail", "blocked"] = Field(description="Overall validation result.")
    command: str = Field(description="Primary validation command that was run or should be run next.")
    output_summary: str = Field(description="Concise summary of stdout/stderr or blocking condition.")
    file_to_patch: str | None = Field(default=None, description="Smallest relevant file to patch next, if any.")
    next_command: str | None = Field(default=None, description="Narrowest rerun command after the next fix.")


class PublishReport(BaseModel):
    status: Literal["ready", "published", "blocked"] = Field(description="Publication/install result.")
    summary: str = Field(description="Concise publish/install/live-validation summary.")
    workspace_actions: list[str] = Field(default_factory=list, description="Workspace selection, install, or publish actions taken.")
    validation_prompts: list[str] = Field(default_factory=list, description="Representative live prompts sent after publish.")
    observed_io: list[str] = Field(default_factory=list, description="Observed input/output behavior from live validation.")
    next_steps: list[str] = Field(default_factory=list, description="Immediate follow-up actions after publish or block.")


def _checkpoint_review_tool() -> Any | None:
    if tool is None:
        return None

    @tool(parse_docstring=True)
    def request_checkpoint_review(
        phase: Literal["architecture_review", "pre_publish_review", "post_publish_review"],
        summary: str,
        findings: list[str],
        next_steps: list[str],
        commands: list[str] | None = None,
        files: list[str] | None = None,
        questions_for_human: list[str] | None = None,
    ) -> str:
        """Pause the workflow for a human checkpoint review.

        Use this before moving into a later workflow phase such as publish.
        The caller must summarize the current state, evidence, and proposed next
        steps. If the human rejects the checkpoint, the agent should stop and
        wait for updated guidance.

        Args:
            phase: The named workflow checkpoint being reviewed.
            summary: High-level summary of what was decided, built, or validated so far.
            findings: Key findings, risks, or evidence points the human should review.
            next_steps: The exact next actions the agent wants to take after approval.
            commands: Optional exact commands already run or proposed next.
            files: Optional relevant files created, changed, or proposed.
            questions_for_human: Optional targeted questions for the reviewer.
        """
        rendered_commands = ", ".join(commands or [])
        rendered_files = ", ".join(files or [])
        rendered_questions = " | ".join(questions_for_human or [])
        details = [
            f"Checkpoint: {phase}",
            summary,
            f"Findings: {'; '.join(findings)}" if findings else "",
            f"Next: {'; '.join(next_steps)}" if next_steps else "",
            f"Commands: {rendered_commands}" if rendered_commands else "",
            f"Files: {rendered_files}" if rendered_files else "",
            f"Questions: {rendered_questions}" if rendered_questions else "",
        ]
        return "\n".join(part for part in details if part.strip())

    return request_checkpoint_review

def _main_skill_sources(cwd: Path) -> list[str]:
    _ = cwd
    return ["/skills/builtin/guild-orchestrator-routing/"]


def _skill_sources(cwd: Path, skill_names: list[str]) -> list[str]:
    settings = get_settings()
    sources: list[str] = []
    for skill_name in skill_names:
        sources.append(f"/skills/builtin/{skill_name}/")
    if settings.allow_workspace_local_skills:
        for skill_name in skill_names:
            if (cwd / "skills" / skill_name).is_dir():
                sources.append(f"/skills/project/{skill_name}/")
    return sources


def _scoped_skill_sources(cwd: Path, skill_name: str) -> list[str]:
    return _skill_sources(cwd, ["guild-official-docs", skill_name])


def _implementation_skill_sources(cwd: Path) -> list[str]:
    return _skill_sources(
        cwd,
        [
            "guild-official-docs",
            "guild-sdk-llm-agent",
            "guild-sdk-auto-managed",
            "guild-sdk-self-managed",
        ],
    )


def _cli_skill_sources(cwd: Path) -> list[str]:
    return _skill_sources(
        cwd,
        [
            "guild-official-docs",
            "guild-cli-runbook",
            "guild-cli-troubleshooting",
            "guild-publish-and-versions",
        ],
    )


def _sdk_skill_sources(cwd: Path) -> list[str]:
    return _skill_sources(
        cwd,
        [
            "guild-official-docs",
            "guild-sdk-llm-agent",
            "guild-sdk-auto-managed",
            "guild-sdk-self-managed",
        ],
    )


def _integration_skill_sources(cwd: Path) -> list[str]:
    return _skill_sources(
        cwd,
        [
            "guild-official-docs",
            "guild-integrations",
            "guild-custom-integrations",
        ],
    )


def _workspace_skill_sources(cwd: Path) -> list[str]:
    return _skill_sources(
        cwd,
        [
            "guild-official-docs",
            "guild-workspace-context",
            "guild-workspace-publisher",
        ],
    )


def _subagent_memory_path(name: str) -> str:
    return f"/memories/subagents/{name}.md"


def _subagent_prompt(name: str, body: str, memory_content: str) -> str:
    embedded_memory = memory_content.strip()
    policy = command_policy_metadata(name)
    allowed_commands = ", ".join(policy["allowed_commands"]) if policy["allowed_commands"] else "none"
    return (
        "Use the embedded role memory below as your stable operating guidance for this task. "
        "Do not waste time rediscovering it or searching the filesystem for another copy. "
        "You normally do not need to call `read_file` for role memory at all unless the parent explicitly asks you to revise persisted memory.\n\n"
        f"<role_memory>\n{embedded_memory}\n</role_memory>\n\n"
        "Execution constraints:\n"
        "- Work only inside the active workspace.\n"
        "- Never create artifacts in /tmp, /var, /Users, or other host-absolute roots.\n"
        "- Use relative workspace paths by default.\n"
        "- Default workspace contract: root `README.md` and top-level `agents/` are required.\n"
        "- Track these identifiers explicitly: local builder workspace `/`, local agent repo `/agents/<agent-name>/`, selected remote Guild workspace (if any).\n"
        "- Manual file creation outside `agents/<agent-name>/...` is forbidden unless the parent explicitly says otherwise.\n"
        f"- Guild CLI policy for `{name}`: {policy['notes']} Allowed commands: {allowed_commands}.\n"
        "- If uncertain about command safety or path scope, return a handoff/request instead of guessing.\n\n"
        "Return concise outputs that help the parent agent act. "
        + body
    )


def _build_subagents(cwd: Path, subagent_memories: dict[str, str] | None = None) -> list[dict[str, Any]]:
    if subagent_memories is None:
        from ..infra.deep_agent_resources import SUBAGENT_MEMORY_CONTENTS

        memories = SUBAGENT_MEMORY_CONTENTS
    else:
        memories = subagent_memories
    return [
        {
            "name": "decomposer",
            "description": "Splits a user request into the right set of Guild agents and responsibilities.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "decomposer",
                "Determine the smallest sensible set of Guild agents for the request. Avoid unnecessary orchestration agents and report concise role boundaries.",
                memories.get("decomposer", ""),
            ),
            "skills": _scoped_skill_sources(cwd, "guild-agent-decomposition"),
            "response_format": SpecialistReport,
        },
        {
            "name": "template_selector",
            "description": "Chooses and justifies Guild agent templates per role.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "template_selector",
                "Select between LLM, AUTO_MANAGED_STATE, and BLANK by capability analysis. Write down the reason clearly and reject alternatives briefly.",
                memories.get("template_selector", ""),
            ),
            "skills": _scoped_skill_sources(cwd, "guild-template-selection"),
            "response_format": SpecialistReport,
        },
        {
            "name": "agent_initializer",
            "description": "Creates Guild agent folders, selects the right init flow, and handles per-agent scaffolding setup.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "agent_initializer",
                "Handle per-agent setup only: initialize the target agent under `agents/<name>/`, run Guild init/test/save commands from that agent directory or a validated `--directory agents/<name>` target, and limit manual edits to that initialized agent folder. Never run root-level init and never improvise recovery commands beyond your narrow surface. Return exact created artifacts and the next edits needed. If blocked by exact CLI behavior, hand off to `cli_specialist`. If blocked by template/code-shape concerns, hand off to `sdk_specialist` or `template_selector`.",
                memories.get("agent_initializer", ""),
            ),
            "skills": _skill_sources(cwd, ["guild-official-docs", "guild-cli-runbook", "guild-template-selection"]),
            "response_format": SpecialistReport,
        },
        {
            "name": "workspace_initializer",
            "description": "Creates or selects Guild workspaces and handles workspace-level bootstrap steps.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "workspace_initializer",
                "Handle remote Guild workspace setup only: use Guild workspace commands for workspace create/select/current/get, membership operations, and shared context preparation. Keep the local builder workspace separate from the remote Guild workspace identity, and verify the selected remote workspace explicitly when state matters. Avoid probing local agent repos unless the parent explicitly asks for a local contract check. If the task is planning-only, return the bootstrap sequence directly without scanning or modifying the workspace. If command details are uncertain, hand off to `cli_specialist`. If the task becomes about installed-agent behavior, hand off to `session_specialist`.",
                memories.get("workspace_initializer", ""),
            ),
            "skills": _workspace_skill_sources(cwd),
            "response_format": SpecialistReport,
        },
        {
            "name": "context_specialist",
            "description": "Handles explicit context/memory requests when they cannot stay implicit in the orchestrator flow.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "context_specialist",
                "Stay dormant unless the parent explicitly asks for context placement work. Prefer no additional artifacts under the default workspace contract. If the question becomes about code shape or template semantics, hand off to `sdk_specialist`. If it becomes about workspace publication rules, hand off to `workspace_initializer` or `publisher`.",
                memories.get("context_specialist", ""),
            ),
            "skills": _skill_sources(cwd, ["guild-official-docs", "guild-context-writer", "guild-workspace-context"]),
            "response_format": SpecialistReport,
        },
        {
            "name": "cli_specialist",
            "description": "Specializes in Guild CLI command sequencing, flags, troubleshooting, and publish/version flows.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "cli_specialist",
                "Focus on exact Guild CLI behavior, flags, ordering, troubleshooting, workspace/session inspection, and publish/version flows. Reuse known-good command flows and only refresh docs when command behavior is uncertain or uncommon. Own the canonical command flows for remote workspace create/select/current/get, workspace context commands, per-agent init inside `agents/<name>/`, live workspace chat/session inspection, publish/version commands, and recovery decisions between clone/pull/init when remote state and local scaffolding diverge.",
                memories.get("cli_specialist", ""),
            ),
            "skills": _cli_skill_sources(cwd),
            "response_format": SpecialistReport,
        },
        {
            "name": "sdk_specialist",
            "description": "Specializes in Guild SDK code patterns, template-specific implementation rules, and non-LLM agent shapes.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "sdk_specialist",
                "Focus on Guild SDK implementation details. Match the chosen template precisely, keep tool sets minimal, and fetch official docs before non-LLM or stateful code generation. If the task becomes about editing generated files for the actual product requirements, hand off to `editor`.",
                memories.get("sdk_specialist", ""),
            ),
            "skills": _sdk_skill_sources(cwd),
            "response_format": SpecialistReport,
        },
        {
            "name": "integration_specialist",
            "description": "Designs and validates Guild integrations, credentials requirements, and custom integration choices.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "integration_specialist",
                "Handle service integrations only. Distinguish first-party vs custom integration needs, credentials, and how the agent should use those tools.",
                memories.get("integration_specialist", ""),
            ),
            "skills": _integration_skill_sources(cwd),
            "response_format": SpecialistReport,
        },
        {
            "name": "trigger_specialist",
            "description": "Designs Guild trigger flows and validates whether webhook or scheduled triggers fit the use case.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "trigger_specialist",
                "Handle trigger design only. Decide whether triggers are needed, which type fits, and what command/configuration sequence should be used.",
                memories.get("trigger_specialist", ""),
            ),
            "skills": _skill_sources(cwd, ["guild-official-docs", "guild-triggers", "guild-workspace-publisher"]),
            "response_format": SpecialistReport,
        },
        {
            "name": "session_specialist",
            "description": "Handles Guild chat/session validation, representative prompts, and inspection of installed-agent behavior.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "session_specialist",
                "Focus on live chat and session validation. Prefer workspace-scoped validation when behavior depends on installed agents or shared workspace context. You may use read-only workspace inspection commands (`guild workspace current/get`, `guild workspace agent list`) to confirm the target workspace and installed agents before validating. For non-interactive checks, resolve the workspace identifier first and use `guild chat --workspace <id-or-full-name> --once ...`. Inspect session behavior through session detail/event/task commands, and summarize whether the installed agents behave as intended.",
                memories.get("session_specialist", ""),
            ),
            "skills": _skill_sources(cwd, ["guild-official-docs", "guild-workspace-publisher"]),
            "response_format": PublishReport,
        },
        {
            "name": "documentation_specialist",
            "description": "Updates the workspace README only when it is explicitly needed.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "documentation_specialist",
                "Keep the workspace README accurate when the parent explicitly requests it or when the user asked for operator-facing documentation. Do not create validation reports, deployment reports, or repo/global README edits by default. If the task asks for a documentation plan only, answer directly from the described workflow instead of scanning files first.",
                memories.get("documentation_specialist", ""),
            ),
            "skills": _skill_sources(cwd, ["guild-official-docs", "guild-context-writer", "guild-publish-and-versions"]),
            "response_format": SpecialistReport,
        },
        {
            "name": "editor",
            "description": "Adapts Guild project files to the actual use case and removes generic template output.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "editor",
                "Customize every generated file to the specific use case, constraints, and chosen template. Never leave placeholder text, generic boilerplate, or unchanged scaffold content when the request already provides concrete domain requirements. If the task is asking for an edit plan rather than real file changes, answer with the targeted edit list directly instead of exploring the workspace. If exact SDK semantics are unclear, hand off to `sdk_specialist`.",
                memories.get("editor", ""),
            ),
            "skills": _implementation_skill_sources(cwd),
            "response_format": SpecialistReport,
        },
        {
            "name": "tester",
            "description": "Runs Guild tests and focused validation commands, then summarizes what passed, failed, and what should be rerun next.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "tester",
                "Run the narrowest meaningful validation command, capture exact stdout/stderr, and return pass/fail status plus the smallest next validation step.",
                memories.get("tester", ""),
            ),
            "skills": _skill_sources(cwd, ["guild-official-docs", "guild-cli-runbook", "guild-repair-loop"]),
            "response_format": ValidationReport,
        },
        {
            "name": "validator",
            "description": "Reviews Guild CLI and chat validation output for the next smallest fix.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "validator",
                "Be read-only. Summarize failures, identify the smallest relevant file to patch, and recommend the narrowest rerun command. When the failure text is already provided, work directly from that evidence and avoid filesystem or docs exploration unless the error is genuinely ambiguous.",
                memories.get("validator", ""),
            ),
            "skills": _scoped_skill_sources(cwd, "guild-repair-loop"),
            "response_format": ValidationReport,
        },
        {
            "name": "publisher",
            "description": "Handles workspace installation, shared context publish, and live Guild validation steps.",
            "tools": [],
            "system_prompt": _subagent_prompt(
                "publisher",
                "Focus on Guild publish/version commands, workspace selection and inspection, agent installation/removal, shared context publication, and representative live workspace validation after publish/install.",
                memories.get("publisher", ""),
            ),
            "skills": _scoped_skill_sources(cwd, "guild-workspace-publisher"),
            "response_format": PublishReport,
        },
    ]


def _build_async_subagents() -> list[dict[str, Any]]:
    server_url = os.getenv("WORKBENCH_ASYNC_AGENT_SERVER_URL", "").strip()
    if not server_url:
        return []
    return [
        {
            "name": "async_tester",
            "description": "Runs long Guild validation or regression tasks in the background on a deployed Agent Protocol server.",
            "graph_id": os.getenv("WORKBENCH_ASYNC_TESTER_GRAPH_ID", "tester"),
            "url": server_url,
        },
        {
            "name": "async_publisher",
            "description": "Runs publish, install, and post-publish workspace validation steps in the background on a deployed Agent Protocol server.",
            "graph_id": os.getenv("WORKBENCH_ASYNC_PUBLISHER_GRAPH_ID", "publisher"),
            "url": server_url,
        },
        {
            "name": "async_session_specialist",
            "description": "Runs longer live Guild session evaluation work in the background on a deployed Agent Protocol server.",
            "graph_id": os.getenv("WORKBENCH_ASYNC_SESSION_GRAPH_ID", "session_specialist"),
            "url": server_url,
        },
    ]


def _memory_sources(cwd: Path) -> list[str]:
    _ = cwd
    return [
        "/memories/workspace/GUILD_BUILDER.md",
        "/memories/session/WORKBENCH.md",
        "/policies/compliance.md",
    ]


def _quick_search_tool() -> Any | None:
    """Return a lightweight internet search tool when Tavily is configured."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key or TavilyClient is None:
        return None
    client = TavilyClient(api_key=api_key)

    def quick_search(
        query: str,
        max_results: int = 5,
        topic: Literal["general", "news", "finance"] = "general",
        include_raw_content: bool = False,
    ) -> dict[str, Any]:
        """Quickly search the internet for real-time information."""
        return client.search(
            query=query,
            max_results=max_results,
            topic=topic,
            include_raw_content=include_raw_content,
        )

    return quick_search


def get_interrupt_config(mode_id: SessionMode) -> dict[str, Any]:
    mode_to_interrupt: dict[str, dict[str, Any]] = {
        "ask_before_edits": {
            "edit_file": {"allowed_decisions": ["approve", "reject"]},
            "write_file": {"allowed_decisions": ["approve", "reject"]},
            "write_todos": {"allowed_decisions": ["approve", "reject"]},
            "execute": {"allowed_decisions": ["approve", "reject"]},
            "request_checkpoint_review": {"allowed_decisions": ["approve", "edit", "reject"]},
        },
        "accept_edits": {
            "execute": {"allowed_decisions": ["approve", "reject"]},
            "request_checkpoint_review": {"allowed_decisions": ["approve", "edit", "reject"]},
        },
        "accept_everything": {},
    }
    return mode_to_interrupt[mode_id]


@dataclass(frozen=True)
class AgentSessionContext:
    session_id: str
    cwd: Path
    workspace_mode: WorkspaceMode
    mode: SessionMode
    model: str
    command_timeout_seconds: int

    @property
    def runtime_artifacts_root(self) -> Path:
        settings = get_settings()
        return settings.data_dir / "runtime_artifacts" / self.session_id


class MockCodingAgent:
    """Deterministic local fallback that exercises the same stream surface as Deep Agents."""

    def __init__(self, context: AgentSessionContext) -> None:
        self.context = context

    def stream(self, payload: dict[str, Any], **_: Any) -> Iterable[dict[str, Any]]:
        message = payload.get("messages", [{}])[-1].get("content", "")
        yield {"type": "updates", "ns": (), "data": {"model_request": {"status": "started"}}}
        yield {
            "type": "custom",
            "ns": (),
            "data": {
                "event": "todo",
                "items": [
                    {"id": "understand", "text": "Understand the request", "status": "completed"},
                    {"id": "inspect", "text": "Inspect workspace files", "status": "active"},
                    {"id": "implement", "text": "Prepare implementation changes", "status": "pending"},
                    {"id": "verify", "text": "Run focused verification", "status": "pending"},
                ],
            },
        }
        yield {
            "type": "custom",
            "ns": ("tools:decomposer",),
            "data": {
                "event": "subagent",
                "name": "decomposer",
                "status": "running",
                "summary": f"Inspecting {self.context.cwd}",
            },
        }
        yield {
            "type": "messages",
            "ns": (),
            "data": (
                {"type": "ai", "content": "I will inspect the workspace, plan the edits, and stream each step. "},
                {"langgraph_node": "model_request"},
            ),
        }
        yield {
            "type": "custom",
            "ns": (),
            "data": {
                "event": "tool_call",
                "name": "ls",
                "args": {"path": "."},
                "result": "Workspace listing requested",
            },
        }
        if self.context.mode != "accept_everything":
            yield {
                "type": "custom",
                "ns": (),
                "data": {
                    "event": "approval_required",
                    "tool": "execute",
                    "payload": {"command": "pytest", "cwd": str(self.context.cwd)},
                },
            }
        yield {
            "type": "custom",
            "ns": (),
            "data": {
                "event": "file_change",
                "path": "README.md",
                "operation": "read",
                "summary": "Mock agent inspected the project README.",
            },
        }
        yield {
            "type": "messages",
            "ns": (),
            "data": (
                {
                    "type": "ai",
                    "content": f"Request captured: {message[:140]}. Real Deep Agents streaming will activate when dependencies and model credentials are configured.",
                },
                {"langgraph_node": "model_request"},
            ),
        }
        yield {
            "type": "custom",
            "ns": ("tools:decomposer",),
            "data": {"event": "subagent", "name": "decomposer", "status": "completed", "summary": "Workspace scan complete."},
        }


def _permissions() -> list[Any]:
    if FilesystemPermission is None:
        return []
    return [
        FilesystemPermission(operations=["read", "write"], paths=["/workspace/.env", "/workspace/.env.*"], mode="deny"),
        FilesystemPermission(operations=["read", "write"], paths=["/workspace/**"], mode="allow"),
        FilesystemPermission(operations=["read", "write"], paths=["/memories/**"], mode="allow"),
        FilesystemPermission(operations=["read", "write"], paths=["/skills/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/policies/**"], mode="deny"),
        FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
    ]


def build_agent(
    context: AgentSessionContext,
    *,
    checkpointer: Any | None = None,
    store: Any | None = None,
) -> Any:
    """Build a Deep Agent when installed, otherwise a deterministic mock agent."""

    if context.model.startswith("mock:") or create_deep_agent is None:
        return MockCodingAgent(context)
    if context.workspace_mode == "remote_sandbox":
        return MockCodingAgent(context)

    # Fireworks is OpenAI-compatible. When users select Fireworks models via
    # openai:accounts/fireworks/models/*, map FIREWORKS_* env vars to the
    # OpenAI-compatible env names expected by LangChain adapters.
    if "accounts/fireworks/models/" in context.model:
        if not os.getenv("OPENAI_API_KEY") and os.getenv("FIREWORKS_API_KEY"):
            os.environ["OPENAI_API_KEY"] = str(os.getenv("FIREWORKS_API_KEY"))
        if not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = "https://api.fireworks.ai/inference/v1"

    assert StateBackend is not None
    assert LocalShellBackend is not None
    assert CompositeBackend is not None
    assert StoreBackend is not None

    from ..infra.deep_agent_resources import (
        SUBAGENT_MEMORY_CONTENTS,
        get_checkpointer,
        get_langgraph_store,
        workspace_namespace,
        workspace_subagent_memory,
    )

    resolved_checkpointer = checkpointer if checkpointer is not None else get_checkpointer()
    resolved_store = store if store is not None else get_langgraph_store()
    workspace_ns = workspace_namespace(context.cwd)

    shell_backend = LocalShellBackend(
        root_dir=str(context.cwd),
        virtual_mode=True,
        inherit_env=True,
        env=redact_env(os.environ.copy()),
    )
    large_tool_results_root = context.runtime_artifacts_root / "large_tool_results"
    large_tool_results_root.mkdir(parents=True, exist_ok=True)
    large_tool_results_backend = LocalShellBackend(
        root_dir=str(large_tool_results_root),
        virtual_mode=True,
        inherit_env=True,
        env=redact_env(os.environ.copy()),
    )
    ephemeral_backend = StateBackend()
    session_ns = context.session_id

    # Pass a CompositeBackend instance (not a factory). MemoryMiddleware resolves callable
    # backends by synthesizing ToolRuntime and omits required fields on current langchain.
    backend = CompositeBackend(
        default=shell_backend,
        routes={
            "/subagents/": StoreBackend(
                store=resolved_store,
                namespace=lambda _rt: workspace_ns,
            ),
            "/memories/workspace/": StoreBackend(
                store=resolved_store,
                namespace=lambda _rt: workspace_ns,
            ),
            "/memories/session/": StoreBackend(
                store=resolved_store,
                namespace=lambda _rt: (session_ns,),
            ),
            "/memories/": StoreBackend(
                store=resolved_store,
                namespace=lambda _rt: (session_ns,),
            ),
            "/skills/": StoreBackend(
                store=resolved_store,
                namespace=lambda _rt: (session_ns,),
            ),
            "/policies/": StoreBackend(
                store=resolved_store,
                namespace=lambda _rt: ("workbench",),
            ),
            "/large_tool_results/": large_tool_results_backend,
            "/conversation_history/": ephemeral_backend,
        },
    )

    model: Any = context.model
    if context.model.startswith("openai:") and ChatOpenAI is not None:
        openai_model = context.model.split("openai:", 1)[1]
        chat_kwargs: dict[str, Any] = {
            "model": openai_model,
            "timeout": float(max(context.command_timeout_seconds, 30)),
            "max_retries": 1,
        }
        if "accounts/fireworks/models/" in context.model:
            chat_kwargs["base_url"] = os.getenv("OPENAI_BASE_URL", "https://api.fireworks.ai/inference/v1")
            model = FireworksReasoningChatOpenAI(**chat_kwargs)
        else:
            model = ChatOpenAI(**chat_kwargs)

    if register_harness_profile is not None and HarnessProfile is not None and GeneralPurposeSubagentProfile is not None:
        register_harness_profile(
            context.model,
            HarnessProfile(
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            ),
        )

    subagent_memories = {
        name: workspace_subagent_memory(resolved_store, workspace_ns, name)
        for name in SUBAGENT_MEMORY_CONTENTS
    }

    kwargs: dict[str, Any] = {
        "model": model,
        "system_prompt": SYSTEM_PROMPT,
        "backend": backend,
        "interrupt_on": get_interrupt_config(context.mode),
        "subagents": [*_build_subagents(context.cwd, subagent_memories), *_build_async_subagents()],
        "memory": _memory_sources(context.cwd),
        "skills": _main_skill_sources(context.cwd),
        "store": resolved_store,
        "checkpointer": resolved_checkpointer,
    }
    tools: list[Any] = []
    checkpoint_tool = _checkpoint_review_tool()
    if checkpoint_tool is not None:
        tools.append(checkpoint_tool)
    quick_search_tool = _quick_search_tool()
    if quick_search_tool is not None:
        tools.append(quick_search_tool)
    if tools:
        kwargs["tools"] = tools
    # Deep Agents 0.5.x permission middleware does not yet support command-capable
    # backends. Keep shell safety on the backend boundary through workspace root
    # scoping, env redaction, and interrupt_on execute approvals.
    if os.getenv("WORKBENCH_ENABLE_DEEPAGENTS_PERMISSIONS") == "true":
        kwargs["permissions"] = _permissions()
    return create_deep_agent(**kwargs)
