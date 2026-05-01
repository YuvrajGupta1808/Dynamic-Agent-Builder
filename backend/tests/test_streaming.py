from pathlib import Path
import time

from agent_workbench.domain.agents import _build_subagents, _main_skill_sources, _memory_sources
from agent_workbench.domain.models import ChatMessage, RunStreamRequest, SessionRecord
from agent_workbench.infra.deep_agent_resources import ensure_session_store_seeded, get_langgraph_store, workspace_namespace
from agent_workbench.infra.session_store import SessionStore
from agent_workbench.services.streaming import (
    EventSequencer,
    InterruptDecisionBroker,
    messages_for_agent_run,
    normalize_chunk,
    stream_run,
)


def test_normalize_token_chunk(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    events = normalize_chunk(
        {"type": "messages", "ns": (), "data": ({"type": "ai", "content": "hello"}, {})},
        sequencer,
        store,
    )
    assert events[0].type == "token"
    assert events[0].message == "hello"


def test_normalize_thinking_chunk(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    events = normalize_chunk(
        {"type": "messages", "ns": (), "data": ({"type": "ai", "thinking": "considering options"}, {})},
        sequencer,
        store,
    )
    assert events[0].type == "thinking"
    assert events[0].message == "considering options"


def test_normalize_chunk_uses_lc_agent_name_as_source(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    events = normalize_chunk(
        {
            "type": "messages",
            "ns": ("tools:task",),
            "data": (
                {"type": "ai", "content": "subagent output"},
                {"lc_agent_name": "sdk_specialist"},
            ),
        },
        sequencer,
        store,
    )
    assert events[0].source == "sdk_specialist"
    assert events[0].message == "subagent output"


def test_normalize_subagent_custom_event_uses_subagent_name_as_source(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    events = normalize_chunk(
        {
            "type": "custom",
            "ns": ("tools:decomposer",),
            "data": {"event": "subagent", "name": "decomposer", "status": "running", "summary": "Planning"},
        },
        sequencer,
        store,
    )
    assert events[0].type == "subagent"
    assert events[0].source == "decomposer"


def test_normalize_messages_reasoning_not_duplicated_across_messages_and_updates(tmp_path: Path) -> None:
    """Dual-stream runs pass emit_update_tokens=False; thinking should come from updates only."""
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    msg_chunk = {
        "type": "messages",
        "ns": (),
        "data": (
            {"type": "ai", "additional_kwargs": {"reasoning_content": "incremental"}},
            {},
        ),
    }
    assert all(e.type != "thinking" for e in normalize_chunk(msg_chunk, sequencer, store, emit_update_tokens=False))

    updates_chunk = {
        "type": "updates",
        "ns": (),
        "data": {
            "model_request": {
                "messages": [
                    {"type": "ai", "additional_kwargs": {"reasoning_content": "canonical reasoning"}},
                ]
            }
        },
    }
    up_events = normalize_chunk(updates_chunk, sequencer, store, emit_update_tokens=False)
    assert any(e.type == "thinking" and e.message == "canonical reasoning" for e in up_events)

    from_messages_only = normalize_chunk(msg_chunk, sequencer, store, emit_update_tokens=True)
    assert any(e.type == "thinking" and e.message == "incremental" for e in from_messages_only)


def test_normalize_updates_token_toggle(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    chunk = {
        "type": "updates",
        "ns": (),
        "data": {
            "model_request": {
                "messages": [
                    {"type": "ai", "content": "assistant text"},
                ]
            }
        },
    }

    with_tokens = normalize_chunk(chunk, sequencer, store, emit_update_tokens=True)
    assert any(event.type == "token" and event.message == "assistant text" for event in with_tokens)

    without_tokens = normalize_chunk(chunk, sequencer, store, emit_update_tokens=False)
    assert all(event.type != "token" for event in without_tokens)


def test_normalize_updates_reasoning_promoted_only_when_enabled(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    chunk = {
        "type": "updates",
        "ns": (),
        "data": {
            "model_request": {
                "messages": [
                    {"type": "ai", "thinking": "model reasoning"},
                ]
            }
        },
    }

    with_tokens = normalize_chunk(chunk, sequencer, store, emit_update_tokens=True)
    assert any(event.type == "token" and event.message == "model reasoning" for event in with_tokens)

    without_tokens = normalize_chunk(chunk, sequencer, store, emit_update_tokens=False)
    assert all(event.type != "token" for event in without_tokens)


def test_approval_event_creates_interrupt(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    events = normalize_chunk(
        {"type": "custom", "ns": (), "data": {"event": "approval_required", "tool": "execute", "payload": {"command": "pytest"}}},
        sequencer,
        store,
    )
    assert events[0].type == "approval_required"
    assert events[0].data["tool"] == "execute"


def test_updates_interrupt_variant_emits_approval_required(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    events = normalize_chunk(
        {
            "type": "updates",
            "ns": (),
            "data": {
                "__interrupt__": [
                    {
                        "value": {
                            "action_requests": [
                                {"name": "execute", "args": {"command": "pwd", "cwd": "/workspace"}}
                            ]
                        }
                    }
                ]
            },
            "_workbench_interrupts": [
                {"interruptId": "intr-1", "tool": "execute", "payload": {"command": "pwd", "cwd": "/workspace"}}
            ],
        },
        sequencer,
        store,
    )
    assert any(event.type == "approval_required" for event in events)
    approval = next(event for event in events if event.type == "approval_required")
    assert approval.data["interruptId"] == "intr-1"
    assert approval.data["tool"] == "execute"
    assert approval.data["allowedDecisions"] == ["approve", "reject"]


def test_updates_interrupt_variant_preserves_allowed_decisions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sequencer = EventSequencer("run-1", "session-1")
    events = normalize_chunk(
        {
            "type": "updates",
            "ns": (),
            "data": {
                "__interrupt__": [
                    {
                        "value": {
                            "action_requests": [
                                {
                                    "name": "request_checkpoint_review",
                                    "args": {
                                        "phase": "architecture_review",
                                        "summary": "Two-agent design is ready.",
                                        "findings": ["support_frontline uses LLM"],
                                        "next_steps": ["Scaffold the chosen agents"],
                                    },
                                }
                            ],
                            "review_configs": [
                                {
                                    "action_name": "request_checkpoint_review",
                                    "allowed_decisions": ["approve", "edit", "reject"],
                                }
                            ],
                        }
                    }
                ]
            },
            "_workbench_interrupts": [
                {
                    "interruptId": "intr-2",
                    "tool": "request_checkpoint_review",
                    "payload": {
                        "phase": "architecture_review",
                        "summary": "Two-agent design is ready.",
                        "findings": ["support_frontline uses LLM"],
                        "next_steps": ["Scaffold the chosen agents"],
                    },
                    "allowedDecisions": ["approve", "edit", "reject"],
                }
            ],
        },
        sequencer,
        store,
    )
    approval = next(event for event in events if event.type == "approval_required")
    assert approval.data["tool"] == "request_checkpoint_review"
    assert approval.data["allowedDecisions"] == ["approve", "edit", "reject"]


def test_interrupt_decision_broker_supports_structured_decisions() -> None:
    broker = InterruptDecisionBroker()
    broker.register("run-1", "intr-1")
    decision = {"type": "edit", "edited_action": {"name": "request_checkpoint_review", "args": {"phase": "architecture_review"}}}
    assert broker.publish("run-1", "intr-1", decision) is True
    assert broker.wait_for("run-1", "intr-1", timeout_seconds=1.0) == decision


def test_interrupt_decision_broker_waits_for_decision() -> None:
    broker = InterruptDecisionBroker()
    broker.register("run-1", "intr-1")
    assert broker.publish("run-1", "intr-1", "approve") is True
    assert broker.wait_for("run-1", "intr-1", timeout_seconds=1.0) == "approve"


def test_interrupt_decision_broker_reuses_recent_duplicate_decision() -> None:
    broker = InterruptDecisionBroker()
    broker.register("run-1", "intr-1", tool="execute", payload={"command": "mkdir -p agents"})
    decision = {"type": "approve"}
    assert broker.publish("run-1", "intr-1", decision) is True
    assert broker.reuse_recent_decision("run-1", "execute", {"command": "mkdir -p agents"}) == decision


def test_stream_run_keeps_subagent_handoffs_alive(monkeypatch, tmp_path: Path) -> None:
    class FakeDelegatingAgent:
        def stream(self, *_args, **_kwargs):
            yield {
                "type": "messages",
                "ns": (),
                "data": (
                    {
                        "type": "ai",
                        "content": "",
                        "tool_call_chunks": [
                            {
                                "name": "task",
                                "args": {
                                    "subagent_type": "decomposer",
                                    "description": "Break the request into the right Guild agents.",
                                },
                            }
                        ],
                    },
                    {},
                ),
            }
            time.sleep(0.2)
            yield {
                "type": "messages",
                "ns": ("tools:task",),
                "data": (
                    {"type": "ai", "content": "Decomposition complete."},
                    {"lc_agent_name": "decomposer"},
                ),
            }

    monkeypatch.setattr("agent_workbench.services.streaming.build_agent", lambda _context: FakeDelegatingAgent())
    monkeypatch.setattr("agent_workbench.services.streaming.ensure_session_store_seeded", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("agent_workbench.services.streaming.get_langgraph_store", lambda: object())
    monkeypatch.setenv("WORKBENCH_STREAM_QUEUE_POLL_SECONDS", "0.05")
    monkeypatch.setenv("WORKBENCH_STREAM_IDLE_WARNING_SECONDS", "0.05")
    monkeypatch.setenv("WORKBENCH_STREAM_HARD_TIMEOUT_SECONDS", "0.15")
    monkeypatch.setenv("WORKBENCH_STREAM_SUBAGENT_HEARTBEAT_SECONDS", "0.05")
    monkeypatch.setenv("WORKBENCH_STREAM_SUBAGENT_TIMEOUT_SECONDS", "0.5")

    store = SessionStore(tmp_path)
    session = store.create_session(
        session_id="session-1",
        cwd=str(tmp_path),
        workspace_mode="local",
        mode="accept_edits",
        model="mock:deterministic",
    )
    chunks = list(
        stream_run(
            session=session,
            request=RunStreamRequest(message="Build the support workspace"),
            run_id="run-1",
            store=store,
            command_timeout_seconds=1,
        )
    )
    body = "".join(chunks)
    assert "Subagent stalled" not in body
    assert '"type":"subagent"' in body
    assert '"waiting":true' in body
    assert "Decomposition complete." in body
    assert "event: done" in body


def test_messages_for_agent_run_prefers_messages_list() -> None:
    req = RunStreamRequest(
        message="ignored",
        messages=[
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello"),
            ChatMessage(role="user", content="again"),
        ],
    )
    out = messages_for_agent_run(req)
    assert len(out) == 3
    assert out[-1]["role"] == "user"
    assert out[-1]["content"] == "again"


def test_messages_for_agent_run_fallback_message_only() -> None:
    out = messages_for_agent_run(RunStreamRequest(message="solo"))
    assert out == [{"role": "user", "content": "solo"}]


def test_langgraph_store_session_seed_idempotent() -> None:
    sid = "session-seed-test-001"
    store = get_langgraph_store()
    ensure_session_store_seeded(store, sid)
    ensure_session_store_seeded(store, sid)
    assert store.get((sid,), "/memories/session/WORKBENCH.md") is not None
    assert store.get((sid,), "/memories/WORKBENCH.md") is not None
    assert store.get((sid,), "/skills/workbench-hint/SKILL.md") is not None
    assert store.get((sid,), "/skills/guild-orchestrator-routing/SKILL.md") is not None
    assert store.get((sid,), "/skills/builtin/guild-orchestrator-routing/SKILL.md") is not None
    assert store.get((sid,), "/skills/guild-official-docs/SKILL.md") is not None
    assert store.get((sid,), "/skills/builtin/guild-official-docs/SKILL.md") is not None
    assert store.get((sid,), "/skills/guild-template-selection/SKILL.md") is not None
    assert store.get((sid,), "/skills/builtin/guild-template-selection/SKILL.md") is not None
    assert store.get((sid,), "/skills/guild-sdk-llm-agent/SKILL.md") is not None


def test_langgraph_store_seeds_workspace_memory(tmp_path: Path) -> None:
    sid = "session-seed-test-workspace"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    store = get_langgraph_store()
    ensure_session_store_seeded(store, sid, workspace_root)
    ns = workspace_namespace(workspace_root)
    builder = store.get(ns, "/memories/workspace/GUILD_BUILDER.md")
    assert builder is not None
    assert "Do not use `quick_search` for Guild docs" in str(builder.value["content"])
    cli = store.get(ns, "/memories/workspace/GUILD_CLI_BASELINE.md")
    assert cli is not None
    assert "guild agent init --name <agent-name> --template <template>" in str(cli.value["content"])
    editor = store.get(ns, "/memories/workspace/IMPLEMENTATION_EDITOR.md")
    assert editor is not None
    assert "do not leave generic README, PROMPT, CONTEXT, or WORKFLOW content" in str(editor.value["content"])
    docs_cache = store.get(ns, "/memories/workspace/GUILD_DOCS_CACHE.md")
    assert docs_cache is not None
    subagent_memory = store.get(ns, "/memories/subagents/editor.md")
    assert subagent_memory is not None
    assert "turn generated scaffolds into use-case-specific artifacts" in str(subagent_memory.value["content"])
    subagent_alias = store.get(ns, "/subagents/editor.md")
    assert subagent_alias is not None
    assert "turn generated scaffolds into use-case-specific artifacts" in str(subagent_alias.value["content"])
    cli_specialist_memory = store.get(ns, "/memories/subagents/cli_specialist.md")
    assert cli_specialist_memory is not None
    assert "Guild CLI sequencing, flags, and troubleshooting" in str(cli_specialist_memory.value["content"])
    tester_memory = store.get(ns, "/memories/subagents/tester.md")
    assert tester_memory is not None
    assert "Run the narrowest useful validation command" in str(tester_memory.value["content"])
    documentation_memory = store.get(ns, "/memories/subagents/documentation_specialist.md")
    assert documentation_memory is not None
    assert "repo README" in str(documentation_memory.value["content"])


def test_langgraph_store_syncs_workspace_skill_overrides(tmp_path: Path) -> None:
    sid = "session-seed-test-override"
    workspace_root = tmp_path / "workspace"
    skill_dir = workspace_root / "skills" / "guild-template-selection"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        """---
name: guild-template-selection
description: Override description
---

# guild-template-selection

Project override.
""",
        encoding="utf-8",
    )
    store = get_langgraph_store()
    ensure_session_store_seeded(store, sid, workspace_root)
    skill = store.get((sid,), "/skills/guild-template-selection/SKILL.md")
    assert skill is not None
    assert "Override description" in str(skill.value["content"])
    layered = store.get((sid,), "/skills/project/guild-template-selection/SKILL.md")
    assert layered is not None
    assert "Override description" in str(layered.value["content"])


def test_subagent_roster_excludes_removed_defaults(tmp_path: Path) -> None:
    subagents = _build_subagents(tmp_path)
    names = [subagent["name"] for subagent in subagents]
    assert "general-purpose" not in names
    assert "docs_researcher" not in names
    assert "editor" in names
    assert "cli_specialist" in names
    assert "documentation_specialist" in names
    editor_prompt = next(subagent["system_prompt"] for subagent in subagents if subagent["name"] == "editor")
    assert "Do not waste time rediscovering it or searching the filesystem for another copy." in editor_prompt
    assert "turn generated scaffolds into use-case-specific artifacts" in editor_prompt


def test_main_agent_loads_only_orchestrator_skill(tmp_path: Path) -> None:
    skills = _main_skill_sources(tmp_path)
    assert skills == ["/skills/builtin/guild-orchestrator-routing/"]


def test_main_agent_memory_stays_router_focused(tmp_path: Path) -> None:
    memories = _memory_sources(tmp_path)
    assert "/memories/workspace/GUILD_BUILDER.md" in memories
    assert "/memories/session/WORKBENCH.md" in memories
    assert "/memories/workspace/GUILD_CLI_BASELINE.md" not in memories
    assert "/memories/workspace/IMPLEMENTATION_EDITOR.md" not in memories
    assert "/memories/workspace/GUILD_DOCS_CACHE.md" not in memories


def test_mock_stream_emits_done(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = SessionRecord(
        id="session-1",
        cwd=str(tmp_path),
        workspaceMode="local",
        mode="accept_everything",
        model="mock:deterministic",
        createdAt="2026-04-27T00:00:00+00:00",
    )
    store.create_session(
        session_id=session.id,
        cwd=session.cwd,
        workspace_mode=session.workspace_mode,
        mode=session.mode,
        model=session.model,
    )
    run_id = store.create_run(session.id)
    chunks = list(
        stream_run(
            session=session,
            request=RunStreamRequest(message="hello"),
            run_id=run_id,
            store=store,
            command_timeout_seconds=120,
        )
    )
    assert any("event: done" in chunk for chunk in chunks)


def test_mock_stream_multiturn_messages_payload(tmp_path: Path) -> None:
    """Mock agent echoes the latest user content; transcript includes prior turns."""
    store = SessionStore(tmp_path)
    session = SessionRecord(
        id="session-mt",
        cwd=str(tmp_path),
        workspaceMode="local",
        mode="accept_everything",
        model="mock:deterministic",
        createdAt="2026-04-27T00:00:00+00:00",
    )
    store.create_session(
        session_id=session.id,
        cwd=session.cwd,
        workspace_mode=session.workspace_mode,
        mode=session.mode,
        model=session.model,
    )
    run_id = store.create_run(session.id)
    req = RunStreamRequest(
        message="third",
        messages=[
            ChatMessage(role="user", content="first"),
            ChatMessage(role="assistant", content="reply one"),
            ChatMessage(role="user", content="second"),
            ChatMessage(role="assistant", content="reply two"),
            ChatMessage(role="user", content="third"),
        ],
    )
    chunks = list(
        stream_run(
            session=session,
            request=req,
            run_id=run_id,
            store=store,
            command_timeout_seconds=120,
        )
    )
    body = "".join(chunks)
    assert "third" in body
    assert "Request captured" in body
