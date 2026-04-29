from pathlib import Path

from agent_workbench.core.config import Settings
from agent_workbench.domain.models import RunStreamRequest, SessionRecord
from agent_workbench.infra.session_store import SessionStore
from agent_workbench.services.streaming import EventSequencer, normalize_chunk, stream_run


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
