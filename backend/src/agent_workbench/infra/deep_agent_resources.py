"""Process-wide LangGraph checkpointer and Deep Agents store (memory doc alignment)."""

from __future__ import annotations

import hashlib
import re
from threading import Lock
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.store.memory import InMemoryStore

from ..core.config import get_settings
from .guild_builder_template import SKILL_FILES

_lock = Lock()
_checkpointer: Any | None = None
_store: Any | None = None


SUBAGENT_MEMORY_CONTENTS: dict[str, str] = {
    "decomposer": """## Decomposer memory
Choose the smallest sensible set of Guild agents for the use case. Avoid inventing orchestrator agents or extra specialists unless the task boundaries are truly different. No Guild CLI. No file writes.
""",
    "template_selector": """## Template selector memory
Choose `LLM`, `AUTO_MANAGED_STATE`, or `BLANK` by capability analysis, not habit. If the answer is likely non-LLM, check official docs first. Return the chosen template, why it fits, and what alternatives were rejected. No Guild CLI. No file writes.
""",
    "agent_initializer": """## Agent initializer memory
You handle per-agent setup only. Make sure the target folder is under `agents/<agent-name>/`, create that local directory before init, and run `guild agent init` only inside that directory or with a validated `--directory agents/<agent-name>` target. Never run Guild agent init at the builder workspace root. Do not improvise CLI recovery, command discovery, cloning, or troubleshooting; if command details or recovery strategy are uncertain, hand back a crisp request for `cli_specialist`. Limit manual edits to code inside initialized agent folders. If implementation shape is unclear, hand back a crisp request for `sdk_specialist`.
""",
    "workspace_initializer": """## Workspace initializer memory
You handle remote Guild workspace setup only. Focus on Guild workspace creation, listing, selection, current-workspace verification, workspace inspection, workspace membership operations, and shared workspace context flows. Always distinguish the selected remote Guild workspace from the local builder workspace on disk. Do not probe the local repo with generic shell discovery; the local builder workspace contract is already root `README.md`, `agents/`, and `agents/README.md`. If installed-agent behavior becomes the question, hand back a request for `session_specialist`.
""",
    "context_specialist": """## Context specialist memory
Stay dormant unless the parent explicitly asks for context placement. Under the default contract, prefer no additional workspace artifacts. If the issue is code-shape or template-specific, hand back a request for `sdk_specialist`.
""",
    "cli_specialist": """## CLI specialist memory
You are responsible for Guild CLI sequencing, flags, troubleshooting, and recovery decisions. Reuse `/memories/workspace/GUILD_CLI_BASELINE.md` first. Avoid repeated `guild --help` discovery for common commands. Report exact commands, working directories, and outcomes. Canonical flows to anchor on:
- remote workspace create/select: `guild workspace list` -> `guild workspace create <name>` or `guild workspace select <id-or-name>` -> `guild workspace current` or `guild workspace get <identifier>` to verify state
- per-agent local init: create or enter `agents/<agent-name>/` -> `guild agent init --name <agent-name> --template <template>`
- add a saved agent into a remote workspace: `guild workspace agent add <identifier>`
- shared workspace context flow: `guild workspace context list/get/edit/publish`
- live workspace validation flow: `guild chat --workspace <identifier>` plus `guild session list/get/events/tasks/send`
- publish/version flow: `guild agent publish`, `guild agent publish --wait`, `guild agent unpublish`, `guild agent versions`
- recovery when a remote agent exists but local scaffolding is missing: decide between `guild agent clone` and a fresh init before handing one exact command back to `agent_initializer`
""",
    "sdk_specialist": """## SDK specialist memory
You handle Guild SDK implementation details. Match the chosen template exactly, keep tool sets minimal, and fetch official docs before non-LLM or stateful code generation. If the task turns into adapting scaffold content for the business use case, hand back a request for `editor`.
""",
    "integration_specialist": """## Integration specialist memory
You handle first-party and custom Guild integrations, credential expectations, and tool-surface decisions. Distinguish clearly between integration design and ordinary agent prompting.
""",
    "trigger_specialist": """## Trigger specialist memory
You handle Guild trigger design only. Decide whether triggers are needed, whether webhook or time-based triggers fit, and what configuration sequence should be used.
""",
    "session_specialist": """## Session specialist memory
You handle live Guild chat and session validation for deployed workspaces and installed agents. Prefer workspace-scoped validation when the behavior being checked depends on multiple installed agents or shared context. You may inspect the current workspace, workspace details, and installed-agent list as read-only validation setup. Before using `guild chat --workspace`, resolve the workspace identifier via `guild workspace current` or `guild workspace get`, and use `--once` for non-interactive command execution. Use representative prompts, inspect session lists/details/events/tasks, and summarize whether installed agents behave as intended. Capture exact example inputs and outputs when the user asks for validation evidence. If the task becomes about workspace creation, selection changes, installation, or context publication, hand back a request for `workspace_initializer` or `publisher`.
""",
    "documentation_specialist": """## Documentation specialist memory
You keep operator-facing docs current. Maintain the active workspace `README.md` and `agents/README.md`. Repository root/global `README.md` is forbidden by default and may only be edited when the user explicitly requests it in the current run. Do not create validation or deployment side artifacts by default.
""",
    "editor": """## Editor memory
Your job is to turn generated scaffolds into use-case-specific artifacts. Read `/memories/workspace/IMPLEMENTATION_EDITOR.md` first when you need workspace-level editing rules. Rewrite generic template content when concrete business requirements already exist. Do not leave placeholder prompts, READMEs, or workflows unchanged. If exact SDK semantics are uncertain, hand back a request for `sdk_specialist`.
""",
    "tester": """## Tester memory
Run the narrowest useful validation command. Capture exact stdout/stderr. Return what passed, what failed, and the single best next validation command. Avoid broad command spam.
""",
    "validator": """## Validator memory
You are read-only. Analyze failures, identify the smallest file to patch, and recommend the narrowest rerun. Do not propose large refactors when a smaller fix can prove the issue.
""",
    "publisher": """## Publisher memory
Handle only post-validation Guild steps: publish/version operations, workspace selection/inspection, agent installation/removal, shared context publish, trigger setup, and representative live workspace validation. Do not publish until local validation is good enough. Verify the selected remote workspace explicitly before install/publish steps, and record representative input/output behavior after publish when the user wants evidence of how the installed workspace behaved.
""",
}


def _create_file_data(content: str) -> dict[str, Any]:
    try:
        from deepagents.backends.utils import create_file_data

        return create_file_data(content)
    except Exception:
        return {"content": content}


def get_checkpointer() -> Any:
    """Shared in-memory checkpointer so thread_id survives across HTTP streams."""
    global _checkpointer
    with _lock:
        if _checkpointer is None:
            from langgraph.checkpoint.memory import MemorySaver

            _checkpointer = MemorySaver()
        return _checkpointer


def get_langgraph_store() -> Any:
    """Shared store backing `/memories/`, `/skills/`, and `/policies/` StoreBackend routes."""
    global _store
    with _lock:
        if _store is None:
            from langgraph.store.memory import InMemoryStore

            store = InMemoryStore()
            _seed_org_policies(store)
            _store = store
        return _store


def workspace_namespace(workspace_root: Path) -> tuple[str, str]:
    """Stable store namespace for a workspace across sessions."""
    resolved = str(workspace_root.resolve())
    label = workspace_root.name or "workspace"
    safe_label = re.sub(r"[^A-Za-z0-9._@+\-:~]+", "_", label).strip("_") or "workspace"
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return ("workspace", f"{safe_label}:{digest}")


def _seed_org_policies(store: InMemoryStore | Any) -> None:
    ns = ("workbench",)
    key = "/policies/compliance.md"
    if store.get(ns, key) is None:
        store.put(
            ns,
            key,
            _create_file_data(
                """## Local workbench policies
- Do not exfiltrate secrets from .env or credential files.
- Prefer minimal diffs and explain risky commands before execution.
- Treat Guild workspace/session/trigger behavior as the runtime control plane when building Guild agents here.
"""
            ),
        )


def ensure_session_store_seeded(store: Any, session_id: str, workspace_root: Path | None = None) -> None:
    """Per-session long-term memory and skill seeds (namespaced store); idempotent."""
    ns = (session_id,)

    mem_key = "/memories/session/WORKBENCH.md"
    if store.get(ns, mem_key) is None:
        store.put(
            ns,
            mem_key,
            _create_file_data(
                """## Session memory
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
"""
            ),
        )
    # Backward-compatible alias for older code/notes that still read this path.
    legacy_mem_key = "/memories/WORKBENCH.md"
    if store.get(ns, legacy_mem_key) is None:
        store.put(ns, legacy_mem_key, _create_file_data(store.get(ns, mem_key).value["content"]))
    if workspace_root is not None:
        _seed_workspace_memory(store, workspace_namespace(workspace_root))
    _seed_base_skills(store, ns)
    _seed_workspace_skills(store, ns, workspace_root)


def _seed_workspace_memory(store: Any, namespace: tuple[str, str]) -> None:
    builder_key = "/memories/workspace/GUILD_BUILDER.md"
    if store.get(namespace, builder_key) is None:
        store.put(
            namespace,
            builder_key,
            _create_file_data(
                """## Guild orchestrator workspace memory
This workspace is for building Guild agents with a routing-first Deep Agent workbench.

Default operating rules:
- Start with a concise todo list.
- Keep the main agent focused on routing, phase order, and quality gates.
- Delegate Guild domain work to specialists instead of loading all domain knowledge into the main agent prompt.
- Do not use `quick_search` for Guild docs, CLI reference, or Guild SDK behavior. Route docs work to the relevant specialist and let it use the official docs skill.
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
"""
            ),
        )

    cli_key = "/memories/workspace/GUILD_CLI_BASELINE.md"
    if store.get(namespace, cli_key) is None:
        store.put(
            namespace,
            cli_key,
            _create_file_data(
                """## Guild CLI baseline
Use this file as the default command memory for common Guild workflows.

Common per-agent flow:
1. `guild auth status`
2. create or enter `agents/<agent-name>/`
3. `guild agent init --name <agent-name> --template <template>`
4. edit generated files under `agents/<agent-name>/...` so they match the actual use case
5. `guild agent test --ephemeral`
6. if needed, patch the smallest file and rerun the test
7. `guild agent save`

Common workspace flow after local validation:
1. `guild workspace list`
2. `guild workspace create <workspace-name>` or `guild workspace select <workspace-name-or-id>`
3. `guild workspace current` or `guild workspace get <workspace-name-or-id>` to verify the selected remote workspace
4. `guild workspace agent add <identifier>`
5. `guild workspace agent list`
6. optional shared context flow with `guild workspace context list/get/edit/publish`
7. optional live validation with `guild workspace current` or `guild workspace get <workspace-name-or-id>` to confirm the identifier, then `guild chat --workspace <workspace-id-or-full-name> --once "<prompt>"` plus `guild session list/get/events/tasks/send`

Do not rediscover these with repeated `guild --help` unless the task depends on an uncommon command or exact CLI edge case.
"""
            ),
        )

    editor_key = "/memories/workspace/IMPLEMENTATION_EDITOR.md"
    if store.get(namespace, editor_key) is None:
        store.put(
            namespace,
            editor_key,
            _create_file_data(
                """## Implementation editor memory
When adapting Guild project files:
- tailor every artifact to the actual user use case
- replace placeholders with concrete domain details
- do not leave generic PROMPT, CONTEXT, or WORKFLOW content after the user has already described the product
- prefer small diffs that make the scaffold usable immediately
- if a template produces boilerplate, rewrite the relevant parts rather than preserving them for later
- keep assumptions explicit and minimal
- do not manually scaffold files outside `agents/<agent-name>/...`

For agent code and prompts:
- match the chosen Guild template
- reflect the actual task boundaries, inputs, outputs, and escalation behavior
- avoid writing "template" or "example" style content unless the user explicitly asked for a stub
"""
            ),
        )

    docs_cache_key = "/memories/workspace/GUILD_DOCS_CACHE.md"
    if store.get(namespace, docs_cache_key) is None:
        store.put(
            namespace,
            docs_cache_key,
            _create_file_data(
                """## Guild docs cache
Use this file to cache short summaries of Guild rules that were fetched from the official docs during this workspace's prior runs.

Write only high-signal reusable notes here:
- command behavior that was verified from official docs
- template selection rules that mattered for this workspace
- workspace publish/install notes
- integration or trigger rules that are likely to be reused

Do not paste full documentation pages here. Store only concise summaries and the source URL you relied on.
"""
            ),
        )

    for name, content in SUBAGENT_MEMORY_CONTENTS.items():
        key = f"/memories/subagents/{name}.md"
        if store.get(namespace, key) is None:
            store.put(namespace, key, _create_file_data(content))
        alias_key = f"/subagents/{name}.md"
        if store.get(namespace, alias_key) is None:
            store.put(namespace, alias_key, _create_file_data(content))


def workspace_subagent_memory(store: Any, namespace: tuple[str, str], name: str) -> str:
    key = f"/memories/subagents/{name}.md"
    item = store.get(namespace, key)
    if item is not None:
        content = item.value.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return SUBAGENT_MEMORY_CONTENTS.get(name, "").strip()


def _seed_base_skills(store: Any, namespace: tuple[str]) -> None:
    hint_key = "/workbench-hint/SKILL.md"
    if store.get(namespace, hint_key) is None:
        store.put(
            namespace,
            hint_key,
            _create_file_data(
                """---
name: workbench-hint
description: Reminds the agent to use the workbench workspace root for file tools and to follow the required README plus `agents/` workspace contract.
---

# workbench-hint

Prefer reading and editing files under the configured workspace path. Use memory files under `/memories/` for durable notes across turns. Follow the default contract: root `README.md`, `agents/`, and `agents/README.md`, with generated agent code under `agents/<agent-name>/...`. Built-in authoring workflows are available virtually under `/skills/`. Fetch official Guild docs before uncommon CLI, non-LLM codegen, integration, trigger, or custom integration work.
"""
            ),
        )

    for relative_path, content in SKILL_FILES.items():
        route_relative = relative_path.removeprefix("/")
        if route_relative.startswith("skills/"):
            route_relative = route_relative[len("skills/") :]
        canonical_key = f"/{route_relative}"
        if store.get(namespace, canonical_key) is None:
            store.put(namespace, canonical_key, _create_file_data(content))

        layered_key = f"/builtin/{route_relative}"
        if store.get(namespace, layered_key) is None:
            store.put(namespace, layered_key, _create_file_data(content))


def _seed_workspace_skills(store: Any, namespace: tuple[str], workspace_root: Path | None) -> None:
    if workspace_root is None:
        return
    if not get_settings().allow_workspace_local_skills:
        return
    skills_root = workspace_root / "skills"
    if not skills_root.is_dir():
        return
    for file_path in sorted(path for path in skills_root.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(workspace_root).as_posix()
        route_relative = relative_path.removeprefix("/")
        if route_relative.startswith("skills/"):
            route_relative = route_relative[len("skills/") :]
        canonical_key = f"/{route_relative}"
        store.put(namespace, canonical_key, _create_file_data(file_path.read_text(encoding="utf-8")))
        layered_key = f"/project/{route_relative}"
        store.put(namespace, layered_key, _create_file_data(file_path.read_text(encoding="utf-8")))
