"""Process-wide LangGraph checkpointer and Deep Agents store (memory doc alignment)."""

from __future__ import annotations

import hashlib
import re
from threading import Lock
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.store.memory import InMemoryStore

from .guild_builder_template import SKILL_FILES

_lock = Lock()
_checkpointer: Any | None = None
_store: Any | None = None


SUBAGENT_MEMORY_CONTENTS: dict[str, str] = {
    "decomposer": """## Decomposer memory
Choose the smallest sensible set of Guild agents for the use case. Avoid inventing orchestrator agents or extra specialists unless the task boundaries are truly different.
""",
    "template_selector": """## Template selector memory
Choose `LLM`, `AUTO_MANAGED_STATE`, or `BLANK` by capability analysis, not habit. If the answer is likely non-LLM, check official docs first. Return the chosen template, why it fits, and what alternatives were rejected.
""",
    "agent_initializer": """## Agent initializer memory
You handle per-agent setup. Make sure the right folder exists, the template choice is already justified, and Guild init commands run from the correct location with the correct naming. If command details are uncertain, hand back a crisp request for `cli_specialist`. If implementation shape is unclear, hand back a crisp request for `sdk_specialist`.
""",
    "workspace_initializer": """## Workspace initializer memory
You handle workspace-level setup only. Focus on Guild workspace creation or selection and the minimum bootstrap needed before installation or validation. If installed-agent behavior becomes the question, hand back a request for `session_specialist`.
""",
    "context_specialist": """## Context specialist memory
Keep always-loaded memory minimal. Put shared cross-agent facts in shared context, role-specific rules in per-agent docs, and larger reusable workflows in skills. Avoid duplicating the same context across files. If the issue is code-shape or template-specific, hand back a request for `sdk_specialist`.
""",
    "cli_specialist": """## CLI specialist memory
You are responsible for Guild CLI sequencing, flags, and troubleshooting. Reuse `/memories/workspace/GUILD_CLI_BASELINE.md` first. Avoid repeated `guild --help` discovery for common commands. Report exact commands, working directories, and outcomes.
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
You handle live Guild chat and session validation. Propose representative prompts, inspect session behavior, and summarize whether installed agents behave as intended. Capture exact example inputs and outputs when the user asks for validation evidence.
""",
    "documentation_specialist": """## Documentation specialist memory
You keep operator-facing docs current. Update the repo README, workspace README, and validation/deployment notes when the build flow, required commands, or observed behavior change materially. Keep docs concise and practical.
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
Handle only post-validation Guild steps: workspace creation/selection, agent installation, shared context publish, trigger setup, and representative live validation. Do not publish until local validation is good enough. Record representative input/output behavior after publish when the user wants evidence of how the installed workspace behaved.
""",
}


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
    from deepagents.backends.utils import create_file_data

    ns = ("workbench",)
    key = "/policies/compliance.md"
    if store.get(ns, key) is None:
        store.put(
            ns,
            key,
            create_file_data(
                """## Local workbench policies
- Do not exfiltrate secrets from .env or credential files.
- Prefer minimal diffs and explain risky commands before execution.
- Treat Guild workspace/session/trigger behavior as the runtime control plane when building Guild agents here.
"""
            ),
        )


def ensure_session_store_seeded(store: Any, session_id: str, workspace_root: Path | None = None) -> None:
    """Per-session long-term memory and skill seeds (namespaced store); idempotent."""
    from deepagents.backends.utils import create_file_data

    ns = (session_id,)

    mem_key = "/memories/session/WORKBENCH.md"
    if store.get(ns, mem_key) is None:
        store.put(
            ns,
            mem_key,
            create_file_data(
                """## Session memory
Use this file for preferences and durable facts for this conversation session.
You may update it when the user asks you to remember something.

When working in a Guild builder workspace:
- Treat the main Deep Agent as an orchestrator, not the holder of all Guild implementation knowledge
- Delegate Guild docs, CLI, SDK, integration, testing, editing, and publish details to the relevant specialist subagents
- Keep validation and publish outcomes in `TEST_RESULTS.md` when you decide to create that file
- Keep post-publish live-validation notes in `VALIDATION_REPORT.md` or `DEPLOYMENT_REPORT.md` when the task is substantial
- Update operator-facing `README.md` files when the orchestration flow or resulting workspace behavior changes materially
- Use explicit checkpoint reviews before moving from architecture -> implementation, local validation -> publish, and publish -> final sign-off
- Do not materialize docs into the workspace unless a long-running task would benefit from a local reference note
"""
            ),
        )
    # Backward-compatible alias for older code/notes that still read this path.
    legacy_mem_key = "/memories/WORKBENCH.md"
    if store.get(ns, legacy_mem_key) is None:
        store.put(ns, legacy_mem_key, create_file_data(store.get(ns, mem_key).value["content"]))
    if workspace_root is not None:
        _seed_workspace_memory(store, workspace_namespace(workspace_root))
    _seed_base_skills(store, ns)
    _seed_workspace_skills(store, ns, workspace_root)


def _seed_workspace_memory(store: Any, namespace: tuple[str, str]) -> None:
    from deepagents.backends.utils import create_file_data

    builder_key = "/memories/workspace/GUILD_BUILDER.md"
    if store.get(namespace, builder_key) is None:
        store.put(
            namespace,
            builder_key,
            create_file_data(
                """## Guild orchestrator workspace memory
This workspace is for building Guild agents with a routing-first Deep Agent workbench.

Default operating rules:
- Start with a concise todo list.
- Keep the main agent focused on routing, phase order, and quality gates.
- Delegate Guild domain work to specialists instead of loading all domain knowledge into the main agent prompt.
- Do not use `quick_search` for Guild docs, CLI reference, or Guild SDK behavior. Route docs work to the relevant specialist and let it use the official docs skill.
- For common Guild work, the normal flow is:
  1. decide how many agents are needed
  2. choose the Guild template and justify it
  3. update the workspace docs/plan so the build is legible
  4. scaffold only the required artifacts
  5. adapt generated files to the real use case
  6. run focused local validation
  7. repair the smallest failure and rerun narrowly
  8. stop for pre-publish checkpoint review with commands, files, and risks
  9. publish/install only after local validation is good enough and the checkpoint is approved
  10. run representative live validation and record the exact inputs/outputs in project docs
- The orchestrator should explicitly pause for `architecture_review`, `pre_publish_review`, and `post_publish_review` instead of one-shotting the entire lifecycle.
- Use `documentation_specialist` whenever README or validation-report updates are needed.
- If async task tools are available in a deployed environment, use them for long-running validation/publish/live-evaluation work only; do not poll immediately after launch.
"""
            ),
        )

    cli_key = "/memories/workspace/GUILD_CLI_BASELINE.md"
    if store.get(namespace, cli_key) is None:
        store.put(
            namespace,
            cli_key,
            create_file_data(
                """## Guild CLI baseline
Use this file as the default command memory for common Guild workflows.

Common per-agent flow:
1. `guild auth status`
2. `guild agent init --name <agent-name> --template <template>`
3. edit generated files so they match the actual use case
4. `guild agent test --ephemeral`
5. if needed, patch the smallest file and rerun the test
6. `guild agent save --message "<message>" --wait --publish`

Common workspace flow after local validation:
1. `guild workspace list`
2. `guild workspace create <workspace-name>` or `guild workspace select <workspace-name-or-id>`
3. `guild workspace agent add <identifier>`
4. `guild workspace agent list`
5. optional live validation with `guild chat --agent <identifier> --workspace <workspace-id>`

Do not rediscover these with repeated `guild --help` unless the task depends on an uncommon command or exact CLI edge case.
"""
            ),
        )

    editor_key = "/memories/workspace/IMPLEMENTATION_EDITOR.md"
    if store.get(namespace, editor_key) is None:
        store.put(
            namespace,
            editor_key,
            create_file_data(
                """## Implementation editor memory
When adapting Guild project files:
- tailor every artifact to the actual user use case
- replace placeholders with concrete domain details
- do not leave generic README, PROMPT, CONTEXT, or WORKFLOW content after the user has already described the product
- prefer small diffs that make the scaffold usable immediately
- if a template produces boilerplate, rewrite the relevant parts rather than preserving them for later
- keep assumptions explicit and minimal

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
            create_file_data(
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
            store.put(namespace, key, create_file_data(content))
        alias_key = f"/subagents/{name}.md"
        if store.get(namespace, alias_key) is None:
            store.put(namespace, alias_key, create_file_data(content))


def workspace_subagent_memory(store: Any, namespace: tuple[str, str], name: str) -> str:
    key = f"/memories/subagents/{name}.md"
    item = store.get(namespace, key)
    if item is not None:
        content = item.value.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return SUBAGENT_MEMORY_CONTENTS.get(name, "").strip()


def _seed_base_skills(store: Any, namespace: tuple[str]) -> None:
    from deepagents.backends.utils import create_file_data

    hint_key = "/skills/workbench-hint/SKILL.md"
    if store.get(namespace, hint_key) is None:
        store.put(
            namespace,
            hint_key,
            create_file_data(
                """---
name: workbench-hint
description: Reminds the agent to use the workbench workspace root for file tools and to prefer AGENTS.md for always-relevant guidance.
---

# workbench-hint

Prefer reading and editing files under the configured workspace path. Use memory files under `/memories/` for durable notes across turns. If the workspace includes `AGENTS.md`, treat it as always-relevant builder guidance. Built-in authoring workflows are available virtually under `/skills/` even when there is no on-disk `skills/` folder yet. Fetch official Guild docs before uncommon CLI, non-LLM codegen, integration, trigger, or custom integration work.
"""
            ),
        )

    for relative_path, content in SKILL_FILES.items():
        canonical_key = f"/{relative_path}" if not relative_path.startswith("/") else relative_path
        if store.get(namespace, canonical_key) is None:
            store.put(namespace, canonical_key, create_file_data(content))

        layered_key = canonical_key.replace("/skills/", "/skills/builtin/", 1)
        if store.get(namespace, layered_key) is None:
            store.put(namespace, layered_key, create_file_data(content))


def _seed_workspace_skills(store: Any, namespace: tuple[str], workspace_root: Path | None) -> None:
    from deepagents.backends.utils import create_file_data

    if workspace_root is None:
        return
    skills_root = workspace_root / "skills"
    if not skills_root.is_dir():
        return
    for file_path in sorted(path for path in skills_root.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(workspace_root).as_posix()
        canonical_key = f"/{relative_path}" if not relative_path.startswith("/") else relative_path
        store.put(namespace, canonical_key, create_file_data(file_path.read_text(encoding="utf-8")))
        layered_key = canonical_key.replace("/skills/", "/skills/project/", 1)
        store.put(namespace, layered_key, create_file_data(file_path.read_text(encoding="utf-8")))
