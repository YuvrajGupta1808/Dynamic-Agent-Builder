from pathlib import Path

from agent_workbench.domain.models import ChatMessage, RunStreamRequest, SessionRecord
from agent_workbench.infra.deep_agent_resources import ensure_session_store_seeded, get_langgraph_store
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


def test_interrupt_decision_broker_waits_for_decision() -> None:
    broker = InterruptDecisionBroker()
    broker.register("run-1", "intr-1")
    assert broker.publish("run-1", "intr-1", "approve") is True
    assert broker.wait_for("run-1", "intr-1", timeout_seconds=1.0) == "approve"


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
    assert store.get((sid,), "/memories/WORKBENCH.md") is not None
    assert store.get((sid,), "/skills/workbench-hint/SKILL.md") is not None


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
