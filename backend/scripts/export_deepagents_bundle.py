#!/usr/bin/env python3
"""Regenerate deploy/guild-builder-deepagent from workbench Python sources.

Run from repo root:
  PYTHONPATH=backend/src python3 backend/scripts/export_deepagents_bundle.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bundle_root() -> Path:
    return _repo_root() / "deploy" / "guild-builder-deepagent"


def _ensure_sys_path() -> None:
    src = _repo_root() / "backend" / "src"
    s = str(src)
    if s not in sys.path:
        sys.path.insert(0, s)


def _skill_name_from_virtual(path: str) -> str | None:
    m = re.match(r"/skills/(?:builtin|project)/([^/]+)/?", path.strip())
    return m.group(1) if m else None


def _json_discipline(model_name: str, schema: dict) -> str:
    compact = json.dumps(schema, indent=2)
    return (
        f"\n\n## Structured output ({model_name})\n\n"
        "End your reply with a single fenced JSON code block (```json ... ```) only, no other text after it. "
        "The JSON must validate against this schema:\n\n"
        f"```json\n{compact}\n```\n"
    )


def _copy_skill_dir(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _export_workbench_memory_skills(bundle: Path) -> None:
    """Parity for store-seeded markdown (see deep_agent_resources._seed_*)."""
    root = bundle / "skills" / "workbench-seeded-memory"
    root.mkdir(parents=True, exist_ok=True)

    (root / "SKILL.md").write_text(
        """---
name: workbench-seeded-memory
description: >-
  Parity pack for local workbench store seeds: compliance, workspace builder memory,
  CLI baseline, editor rules, and docs cache. Read individual *.md files as needed.
metadata:
  domain: guild-builder
  version: "1.0"
---

# workbench-seeded-memory

In the local FastAPI workbench these texts were injected into the LangGraph store under
`/memories/workspace/`, `/memories/session/`, and `/policies/`. In this Deep Agents bundle
they live as normal skill files — read them when you need the same baseline context.
""",
        encoding="utf-8",
    )

    seeds: dict[str, str] = {
        "compliance.md": """## Local workbench policies
- Do not exfiltrate secrets from .env or credential files.
- Prefer minimal diffs and explain risky commands before execution.
- Treat Guild workspace/session/trigger behavior as the runtime control plane when building Guild agents here.
""",
        "WORKBENCH_SESSION.md": """## Session memory
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
""",
        "GUILD_BUILDER.md": """## Guild orchestrator workspace memory
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
""",
        "GUILD_CLI_BASELINE.md": """## Guild CLI baseline
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
""",
        "IMPLEMENTATION_EDITOR.md": """## Implementation editor memory
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
""",
        "GUILD_DOCS_CACHE.md": """## Guild docs cache
Use this file to cache short summaries of Guild rules that were fetched from the official docs during this workspace's prior runs.

Write only high-signal reusable notes here:
- command behavior that was verified from official docs
- template selection rules that mattered for this workspace
- workspace publish/install notes
- integration or trigger rules that are likely to be reused

Do not paste full documentation pages here. Store only concise summaries and the source URL you relied on.
""",
    }
    for name, body in seeds.items():
        (root / name).write_text(body.strip() + "\n", encoding="utf-8")


def _export_workbench_hint(bundle: Path) -> None:
    d = bundle / "skills" / "workbench-hint"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        """---
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
""",
        encoding="utf-8",
    )


def main() -> None:
    _ensure_sys_path()
    from agent_workbench.domain.agents import (
        PublishReport,
        SpecialistReport,
        SYSTEM_PROMPT,
        ValidationReport,
        _build_subagents,
    )
    from agent_workbench.infra.guild_builder_template import SKILL_FILES

    repo = _repo_root()
    bundle = _bundle_root()
    bundle.mkdir(parents=True, exist_ok=True)

    skills_root = bundle / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    for rel, content in SKILL_FILES.items():
        out = bundle / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")

    _export_workbench_memory_skills(bundle)
    _export_workbench_hint(bundle)

    deploy_note = """## Deployment runtime (Deep Agents bundle)

You are running as a LangSmith Deployment bundle, not the local FastAPI workbench.
Filesystem and shell state live in the configured sandbox (see `deepagents.toml`).
The in-process tools `request_checkpoint_review` and optional Tavily `quick_search` from
the Python workbench are replaced here by: (1) human review via LangSmith human-in-the-loop
/ operator workflow outside strict tool parity, and (2) Tavily MCP tools when `mcp.json`
is configured with a valid HTTP Tavily endpoint.

For store-backed texts that the workbench injected under `/memories/workspace/` and
`/policies/`, read the `skills/workbench-seeded-memory/` pack.

"""
    (bundle / "AGENTS.md").write_text(deploy_note + "\n" + SYSTEM_PROMPT.strip() + "\n", encoding="utf-8")

    sub_root = bundle / "subagents"
    if sub_root.exists():
        shutil.rmtree(sub_root)
    sub_root.mkdir(parents=True, exist_ok=True)

    dummy_cwd = repo / "workspaces"
    if not dummy_cwd.is_dir():
        dummy_cwd = repo
    subs = _build_subagents(dummy_cwd.resolve())

    schema_map: dict[str, type] = {
        "SpecialistReport": SpecialistReport,
        "ValidationReport": ValidationReport,
        "PublishReport": PublishReport,
    }

    for spec in subs:
        name = spec["name"]
        desc = spec["description"]
        sys_prompt = spec["system_prompt"]
        rf = spec.get("response_format")
        model_name = rf.__name__ if rf is not None else "SpecialistReport"
        schema_obj = schema_map.get(model_name, SpecialistReport)
        appendix = _json_discipline(model_name, schema_obj.model_json_schema())
        sdir = sub_root / name
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "deepagents.toml").write_text(
            f'[agent]\nname = "{name}"\ndescription = {json.dumps(desc)}\n',
            encoding="utf-8",
        )
        (sdir / "AGENTS.md").write_text(sys_prompt.rstrip() + appendix, encoding="utf-8")

        vpaths: list[str] = list(spec.get("skills") or [])
        sub_skills = sdir / "skills"
        sub_skills.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        for vp in vpaths:
            sid = _skill_name_from_virtual(vp)
            if not sid or sid in seen:
                continue
            seen.add(sid)
            src = skills_root / sid
            if src.is_dir():
                _copy_skill_dir(src, sub_skills / sid)
            else:
                print(f"warn: subagent {name} references missing skill {sid}", file=sys.stderr)

    user_dir = bundle / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "AGENTS.md").write_text(
        (bundle / "skills" / "workbench-seeded-memory" / "WORKBENCH_SESSION.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    print(f"Wrote bundle to {bundle}")


if __name__ == "__main__":
    main()
