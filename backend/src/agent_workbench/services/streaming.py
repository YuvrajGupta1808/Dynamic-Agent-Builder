"""Streaming normalization from LangGraph/Deep Agents chunks to UI events."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections.abc import Generator, Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from ..domain.agents import AgentSessionContext, build_agent
from ..domain.models import ApprovalRecord, RunStreamRequest, SessionRecord, StreamEvent
from ..infra.deep_agent_resources import ensure_session_store_seeded, get_langgraph_store
from ..infra.session_store import SessionStore

MAX_RUN_MESSAGES = 64
MAX_MESSAGE_CHARS = 120_000


class InterruptDecisionBroker:
    """In-memory bridge between interrupt decisions API and active stream workers."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._pending: dict[tuple[str, str], None] = {}
        self._decisions: dict[tuple[str, str], str] = {}

    def register(self, run_id: str, interrupt_id: str) -> None:
        with self._cond:
            self._pending[(run_id, interrupt_id)] = None
            self._cond.notify_all()

    def publish(self, run_id: str, interrupt_id: str, decision: str) -> bool:
        with self._cond:
            key = (run_id, interrupt_id)
            self._decisions[key] = decision
            self._cond.notify_all()
            return key in self._pending

    def wait_for(self, run_id: str, interrupt_id: str, timeout_seconds: float) -> str | None:
        key = (run_id, interrupt_id)
        deadline = time.monotonic() + max(timeout_seconds, 1.0)
        with self._cond:
            while True:
                decision = self._decisions.pop(key, None)
                if decision is not None:
                    self._pending.pop(key, None)
                    return decision
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=remaining)

    def clear_run(self, run_id: str) -> None:
        with self._cond:
            pending_keys = [key for key in self._pending if key[0] == run_id]
            for key in pending_keys:
                self._pending.pop(key, None)
                self._decisions.pop(key, None)


INTERRUPT_BROKER = InterruptDecisionBroker()


def submit_interrupt_decision(run_id: str, interrupt_id: str, decision: str) -> bool:
    """Publish user approval/rejection to an active stream worker."""
    return INTERRUPT_BROKER.publish(run_id, interrupt_id, decision)


def messages_for_agent_run(
    request: RunStreamRequest,
    *,
    workspace_name: str | None = None,
) -> list[dict[str, Any]]:
    """LangChain-compatible chat turns for the Deep Agent graph (multi-turn).

    When ``workspace_name`` is provided, a single-line system note is prepended
    so the agent does not need to call ``pwd`` to discover its workspace.
    Only the human-readable workspace name is exposed; never the host path.
    """
    if request.messages is not None and len(request.messages) > 0:
        trimmed = request.messages[-MAX_RUN_MESSAGES:]
        formatted: list[dict[str, Any]] = []
        for message in trimmed:
            content = message.content
            if isinstance(content, str):
                normalized_content: str | list[dict[str, Any]] = content[:MAX_MESSAGE_CHARS]
            elif isinstance(content, list):
                normalized_content = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = str(block.get("type") or "")
                    if block_type == "text":
                        text = str(block.get("text") or "")
                        normalized_content.append({"type": "text", "text": text[:MAX_MESSAGE_CHARS]})
                    elif block_type == "image_url":
                        image_url = block.get("image_url")
                        if isinstance(image_url, dict):
                            normalized_content.append({"type": "image_url", "image_url": {"url": str(image_url.get("url") or "")}})
                if not normalized_content:
                    normalized_content = [{"type": "text", "text": ""}]
            else:
                normalized_content = ""
            formatted.append({"role": message.role, "content": normalized_content})
        if workspace_name:
            formatted.insert(0, _workspace_context_message(workspace_name))
        return formatted
    base = [{"role": "user", "content": (request.message or "")[:MAX_MESSAGE_CHARS]}]
    if workspace_name:
        base.insert(0, _workspace_context_message(workspace_name))
    return base


def _workspace_context_message(workspace_name: str) -> dict[str, Any]:
    return {
        "role": "system",
        "content": (
            f"Workspace cwd: {workspace_name} (virtual root). "
            "Filesystem tools resolve relative paths under this workspace; "
            "do not call pwd or use host-absolute paths to write workspace files."
        ),
    }


class EventSequencer:
    def __init__(self, run_id: str, session_id: str) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.sequence = 0

    def event(self, event_type: StreamEvent.model_fields["type"].annotation, **kwargs: Any) -> StreamEvent:
        self.sequence += 1
        return StreamEvent(type=event_type, runId=self.run_id, sessionId=self.session_id, sequence=self.sequence, **kwargs)


def to_sse(event: StreamEvent) -> str:
    data = event.model_dump(mode="json", by_alias=True)
    return f"event: {event.type}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _source_from_ns(ns: Any) -> str:
    if not ns:
        return "main"
    if isinstance(ns, str):
        return ns
    for item in ns:
        if isinstance(item, str) and item.startswith("tools:"):
            return item
    return ".".join(str(item) for item in ns)


def _message_content(token: Any) -> str:
    content = token.get("content") if isinstance(token, dict) else getattr(token, "content", "")
    return _extract_text_content(content)


def _message_thinking(token: Any) -> str:
    if isinstance(token, dict):
        direct = token.get("thinking") or token.get("reasoning_content")
        if direct:
            return str(direct)
        extra = token.get("additional_kwargs") or {}
        if isinstance(extra, dict) and extra.get("reasoning_content"):
            return str(extra.get("reasoning_content"))
        # Some providers place reasoning inside structured content blocks.
        content_reasoning = _extract_reasoning_content(token.get("content"))
        if content_reasoning:
            return content_reasoning
        return ""
    direct = getattr(token, "thinking", "") or getattr(token, "reasoning_content", "")
    if direct:
        return str(direct)
    additional_kwargs = getattr(token, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and additional_kwargs.get("reasoning_content"):
        return str(additional_kwargs.get("reasoning_content"))
    content_reasoning = _extract_reasoning_content(getattr(token, "content", ""))
    if content_reasoning:
        return content_reasoning
    return ""


def _token_type(token: Any) -> str:
    if isinstance(token, dict):
        return str(token.get("type") or "")
    return str(getattr(token, "type", "") or "")


def _tool_call_chunks(token: Any) -> list[dict[str, Any]]:
    if isinstance(token, dict):
        return list(token.get("tool_call_chunks") or [])
    return list(getattr(token, "tool_call_chunks", []) or [])


def _message_type(token: Any) -> str:
    if isinstance(token, dict):
        return str(token.get("type") or token.get("role") or "").lower()
    token_type = str(getattr(token, "type", "") or "").lower()
    if token_type:
        return token_type
    role = str(getattr(token, "role", "") or "").lower()
    return role


def _message_tool_calls(token: Any) -> list[dict[str, Any]]:
    raw = token.get("tool_calls") if isinstance(token, dict) else getattr(token, "tool_calls", None)
    if not raw:
        return []
    calls: list[dict[str, Any]] = []
    for call in list(raw):
        if isinstance(call, dict):
            calls.append(call)
            continue
        name = getattr(call, "name", None)
        args = getattr(call, "args", None)
        if name:
            calls.append({"name": name, "args": args or {}})
    return calls


def _extract_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = str(item.get("type") or "")
                if item_type in {"text", "output_text"}:
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
                elif isinstance(item.get("content"), str) and str(item.get("content")).strip():
                    parts.append(str(item.get("content")))
        return "".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return ""


def _extract_reasoning_content(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "reasoning":
            continue
        summary = item.get("summary")
        if not isinstance(summary, list):
            continue
        for entry in summary:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "".join(parts)


def _iter_messages_from_update(update_payload: Any) -> list[Any]:
    if not isinstance(update_payload, dict):
        return []
    messages: list[Any] = []
    for value in update_payload.values():
        if not isinstance(value, dict):
            continue
        maybe_messages = value.get("messages")
        if isinstance(maybe_messages, list):
            messages.extend(maybe_messages)
    return messages


def _collect_interrupt_payloads(value: Any) -> list[Any]:
    payloads: list[Any] = []
    if isinstance(value, dict):
        if "__interrupt__" in value:
            raw = value.get("__interrupt__")
            if isinstance(raw, (list, tuple)):
                payloads.extend(list(raw))
            elif raw is not None:
                payloads.append(raw)
        for child in value.values():
            payloads.extend(_collect_interrupt_payloads(child))
        return payloads
    if isinstance(value, (list, tuple)):
        for item in value:
            payloads.extend(_collect_interrupt_payloads(item))
    return payloads


def _interrupt_payload_to_tool_and_args(raw_interrupt: Any) -> tuple[str, dict[str, Any]]:
    # LangGraph interrupt objects often carry a `.value`; convert to plain data.
    interrupt_value = getattr(raw_interrupt, "value", raw_interrupt)
    if isinstance(interrupt_value, dict):
        action_requests = interrupt_value.get("action_requests")
        if isinstance(action_requests, list) and action_requests:
            first = action_requests[0]
            if isinstance(first, dict):
                tool_name = str(first.get("name") or "execute")
                args = first.get("args")
                if isinstance(args, dict):
                    return tool_name, dict(args)
                return tool_name, {"rawArgs": _safe_data(args)}
        tool = str(interrupt_value.get("tool") or "execute")
        payload = interrupt_value.get("payload")
        if isinstance(payload, dict):
            return tool, payload
    return "execute", {"rawInterrupt": _safe_data(interrupt_value)}


# Read-only shell commands that are safe to auto-approve when the workbench is
# running in `accept_edits` mode. The default set covers harmless probes the
# agent would otherwise gate on (`pwd`, `ls`, `cat`, version checks). Operators
# can override via the WORKBENCH_EXECUTE_SAFELIST env var (comma-separated;
# entries match either the full command or the leading program token). Set the
# env var to an empty string to disable the safelist entirely.
_DEFAULT_EXECUTE_SAFELIST: frozenset[str] = frozenset(
    {
        "pwd",
        "ls",
        "cat",
        "which",
        "python -V",
        "python --version",
        "python3 -V",
        "python3 --version",
    }
)


def _execute_safelist() -> set[str]:
    raw = os.getenv("WORKBENCH_EXECUTE_SAFELIST")
    if raw is None:
        return set(_DEFAULT_EXECUTE_SAFELIST)
    return {token.strip() for token in raw.split(",") if token.strip()}


def _can_auto_approve(tool: str, payload: dict[str, Any]) -> bool:
    if tool != "execute":
        return False
    safelist = _execute_safelist()
    if not safelist:
        return False
    command = str(payload.get("command") or payload.get("cmd") or "").strip()
    if not command:
        return False
    if command in safelist:
        return True
    program = command.split()[0]
    return program in safelist


def _attach_interrupts_to_chunk(chunk: Any) -> tuple[Any, list[dict[str, Any]]]:
    if not isinstance(chunk, dict):
        return chunk, []
    raw_interrupts = _collect_interrupt_payloads(chunk)
    if not raw_interrupts:
        return chunk, []
    prepared: list[dict[str, Any]] = []
    for raw in raw_interrupts:
        tool, payload = _interrupt_payload_to_tool_and_args(raw)
        prepared.append(
            {
                "interruptId": uuid4().hex,
                "tool": tool,
                "payload": payload,
                "rawInterrupt": _safe_data(getattr(raw, "value", raw)),
                "autoApprove": _can_auto_approve(tool, payload),
            }
        )
    enriched_chunk = dict(chunk)
    enriched_chunk["_workbench_interrupts"] = prepared
    return enriched_chunk, prepared


def normalize_chunk(
    chunk: Any,
    sequencer: EventSequencer,
    store: SessionStore,
    *,
    emit_update_tokens: bool = True,
) -> list[StreamEvent]:
    if not isinstance(chunk, dict):
        return [sequencer.event("update", message=str(chunk), data={"raw": repr(chunk)[:1000]})]

    chunk_type = chunk.get("type")
    ns = chunk.get("ns") or ()
    source = _source_from_ns(ns)
    data = chunk.get("data")
    events: list[StreamEvent] = []
    injected_interrupts = chunk.get("_workbench_interrupts")
    if isinstance(injected_interrupts, list) and injected_interrupts:
        for pending in injected_interrupts:
            if not isinstance(pending, dict):
                continue
            interrupt_id = str(pending.get("interruptId") or uuid4().hex)
            tool = str(pending.get("tool") or "execute")
            payload = dict(pending.get("payload") or {})
            if pending.get("rawInterrupt") is not None:
                payload.setdefault("_rawInterrupt", pending.get("rawInterrupt"))
            if pending.get("autoApprove"):
                command_preview = str(payload.get("command") or payload.get("cmd") or "")[:200]
                events.append(
                    sequencer.event(
                        "update",
                        source=source,
                        message=f"Auto-approved safe shell command: {command_preview}".rstrip(": "),
                        data={
                            "event": "auto_approved",
                            "tool": tool,
                            "interruptId": interrupt_id,
                            "command": command_preview,
                        },
                    )
                )
                continue
            approval = ApprovalRecord(
                runId=sequencer.run_id,
                interruptId=interrupt_id,
                tool=tool,
                payload=payload,
            )
            store.create_interrupt(approval)
            events.append(
                sequencer.event(
                    "approval_required",
                    source=source,
                    message=f"Approval required for {approval.tool}",
                    data=approval.model_dump(mode="json", by_alias=True),
                )
            )

    if chunk_type == "messages" and isinstance(data, tuple) and data:
        token = data[0]
        for tool_call in _tool_call_chunks(token):
            if tool_call.get("name"):
                events.append(
                    sequencer.event(
                        "tool_call",
                        source=source,
                        message=f"{source} called {tool_call['name']}",
                        data={"name": tool_call.get("name"), "args": tool_call.get("args", "")},
                    )
                )
        thinking = _message_thinking(token)
        if thinking:
            # LangGraph `stream_mode=["updates","messages",...]` delivers the same reasoning
            # twice: incremental AIMessageChunks on `messages`, then consolidated state on
            # `updates`. The UI showed both (spaced fragments + clean duplicate). When
            # `emit_update_tokens` is False we are in that dual-stream layout—emit thinking
            # only from the `updates` branch below.
            if emit_update_tokens:
                events.append(sequencer.event("thinking", source=source, message=thinking, data={"metadata": data[1] if len(data) > 1 else {}}))
        content = _message_content(token)
        if content and _token_type(token) != "tool":
            events.append(sequencer.event("token", source=source, message=content, data={"metadata": data[1] if len(data) > 1 else {}}))
        elif _token_type(token) == "tool":
            events.append(sequencer.event("tool_call", source=source, message=str(content)[:500], data={"result": content}))
        return events

    if chunk_type == "updates":
        extracted = False
        update_payload = data if isinstance(data, dict) else {}
        for message in _iter_messages_from_update(update_payload):
            msg_type = _message_type(message)
            if msg_type not in {"ai", "assistant", "aimessage", "aimessagechunk"}:
                continue
            # Prefer complete reasoning summaries from update payloads to avoid
            # word-by-word stream chunks in the UI.
            reasoning = _message_thinking(message)
            tool_calls = _message_tool_calls(message)
            if reasoning:
                events.append(sequencer.event("thinking", source=source, message=reasoning))
                extracted = True
            for tool_call in tool_calls:
                if isinstance(tool_call, dict) and tool_call.get("name"):
                    events.append(
                        sequencer.event(
                            "tool_call",
                            source=source,
                            message=f"Tool call: {tool_call.get('name')}",
                            data={"name": tool_call.get("name"), "args": tool_call.get("args", {})},
                        )
                    )
                    extracted = True
            text = _message_content(message)
            if text and emit_update_tokens:
                events.append(sequencer.event("token", source=source, message=text))
                extracted = True
            # Some reasoning models finish with reasoning summaries and no
            # explicit text block. Promote that terminal reasoning to token so
            # the UI always has a final visible assistant response.
            elif emit_update_tokens and reasoning and not tool_calls:
                events.append(sequencer.event("token", source=source, message=reasoning))
                extracted = True
        if not extracted:
            events.append(sequencer.event("update", source=source, message="Graph update", data={"update": _safe_data(data)}))
        return events

    if chunk_type == "custom" and isinstance(data, dict):
        custom_event = data.get("event")
        if custom_event == "todo":
            events.append(sequencer.event("todo", source=source, message="Todo list updated", data={"items": data.get("items", [])}))
        elif custom_event == "subagent":
            events.append(sequencer.event("subagent", source=source, message=data.get("summary"), data=data))
        elif custom_event == "tool_call":
            events.append(sequencer.event("tool_call", source=source, message=f"Tool call: {data.get('name')}", data=data))
        elif custom_event == "file_change":
            events.append(sequencer.event("file_change", source=source, message=data.get("summary"), data=data))
        elif custom_event == "approval_required":
            interrupt_id = str(data.get("interruptId") or uuid4().hex)
            approval = ApprovalRecord(
                runId=sequencer.run_id,
                interruptId=interrupt_id,
                tool=str(data.get("tool") or "unknown"),
                payload=dict(data.get("payload") or {}),
            )
            store.create_interrupt(approval)
            events.append(
                sequencer.event(
                    "approval_required",
                    source=source,
                    message=f"Approval required for {approval.tool}",
                    data=approval.model_dump(mode="json", by_alias=True),
                )
            )
        else:
            events.append(sequencer.event("custom", source=source, message=data.get("status") or "Custom event", data=data))
        return events

    if events:
        return events
    return [sequencer.event("custom", source=source, message="Unhandled stream chunk", data={"chunk": _safe_data(chunk)})]


def _safe_data(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def stream_run(
    *,
    session: SessionRecord,
    request: RunStreamRequest,
    run_id: str,
    store: SessionStore,
    command_timeout_seconds: int,
) -> Generator[str, None, None]:
    sequencer = EventSequencer(run_id, session.id)
    context = AgentSessionContext(
        session_id=session.id,
        cwd=Path(session.cwd),
        workspace_mode=session.workspace_mode,
        mode=request.mode or session.mode,
        model=request.model or session.model,
        command_timeout_seconds=command_timeout_seconds,
    )
    if context.workspace_mode == "remote_sandbox":
        yield to_sse(
            sequencer.event(
                "error",
                message="Remote sandbox mode is configured as an interface but is not enabled for this local install.",
                data={"workspaceMode": context.workspace_mode},
            )
        )
        yield to_sse(sequencer.event("done", message="Run finished with configuration error"))
        store.finish_run(run_id, "error")
        return

    try:
        ensure_session_store_seeded(get_langgraph_store(), session.id)
        agent = build_agent(context)
        stream_messages = messages_for_agent_run(request, workspace_name=context.cwd.name)
        saw_assistant_token = False
        last_reasoning_message = ""
        chunk_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        inactivity_warning_seconds = 45.0
        stream_hard_timeout_seconds = max(float(command_timeout_seconds), inactivity_warning_seconds + 30.0)
        queue_poll_seconds = 5.0
        started_at = time.monotonic()
        last_chunk_at = started_at
        next_idle_warning_at = started_at + inactivity_warning_seconds
        updates_only_stream_mode = False

        def _pump_chunks() -> None:
            nonlocal updates_only_stream_mode
            try:
                next_input: Any = {"messages": stream_messages}
                while True:
                    chunks: Iterable[Any]
                    try:
                        chunks = agent.stream(
                            next_input,
                            stream_mode=["updates", "messages", "custom"],
                            subgraphs=True,
                            version="v2",
                            config={"configurable": {"thread_id": session.id}},
                        )
                    except TypeError:
                        updates_only_stream_mode = True
                        chunks = agent.stream(
                            next_input,
                            stream_mode="updates",
                            subgraphs=True,
                            version="v2",
                        )
                    saw_interrupt = False
                    interrupt_decisions: list[dict[str, Any]] = []
                    for chunk in chunks:
                        enriched_chunk, interrupts = _attach_interrupts_to_chunk(chunk)
                        for pending in interrupts:
                            if pending.get("autoApprove"):
                                continue
                            interrupt_id = str(pending.get("interruptId") or "")
                            if not interrupt_id:
                                continue
                            INTERRUPT_BROKER.register(run_id, interrupt_id)
                        chunk_queue.put(("chunk", enriched_chunk))
                        if not interrupts:
                            continue
                        saw_interrupt = True
                        for pending in interrupts:
                            if pending.get("autoApprove"):
                                interrupt_decisions.append({"type": "approve"})
                                continue
                            interrupt_id = str(pending.get("interruptId") or "")
                            if not interrupt_id:
                                continue
                            decision = INTERRUPT_BROKER.wait_for(
                                run_id,
                                interrupt_id,
                                timeout_seconds=float(max(command_timeout_seconds, 30)),
                            )
                            if decision is None:
                                raise TimeoutError(
                                    f"Timed out waiting for approval decision for interrupt {interrupt_id}."
                                )
                            if decision == "approve":
                                interrupt_decisions.append({"type": "approve"})
                            else:
                                interrupt_decisions.append(
                                    {"type": "reject", "message": "User rejected this tool execution request."}
                                )
                    if not saw_interrupt:
                        break
                    next_input = Command(resume={"decisions": interrupt_decisions})
                chunk_queue.put(("done", None))
            except Exception as exc:  # pragma: no cover - exercised in integration runs
                chunk_queue.put(("error", exc))

        worker = threading.Thread(target=_pump_chunks, daemon=True, name=f"run-stream-{run_id[:8]}")
        worker.start()

        while True:
            try:
                item_type, payload = chunk_queue.get(timeout=queue_poll_seconds)
            except queue.Empty:
                now = time.monotonic()
                idle_seconds = now - last_chunk_at
                total_seconds = now - started_at
                if now >= next_idle_warning_at:
                    yield to_sse(
                        sequencer.event(
                            "update",
                            message="Graph update",
                            data={"idleSeconds": int(idle_seconds), "elapsedSeconds": int(total_seconds)},
                        )
                    )
                    next_idle_warning_at = now + inactivity_warning_seconds
                if total_seconds >= stream_hard_timeout_seconds:
                    timeout_message = (
                        f"Run stalled: no stream events received for {int(idle_seconds)}s. "
                        "Check model connectivity/API key."
                    )
                    yield to_sse(sequencer.event("error", message=timeout_message, data={"errorType": "RunStalledTimeout"}))
                    yield to_sse(sequencer.event("done", message="Run terminated after stall timeout"))
                    store.finish_run(run_id, "error")
                    return
                continue

            if item_type == "error":
                raise payload
            if item_type == "done":
                break
            chunk = payload
            last_chunk_at = time.monotonic()
            next_idle_warning_at = last_chunk_at + inactivity_warning_seconds
            for event in normalize_chunk(
                chunk,
                sequencer,
                store,
                emit_update_tokens=updates_only_stream_mode,
            ):
                if event.type == "token" and (event.message or "").strip():
                    saw_assistant_token = True
                if event.type == "thinking" and (event.message or "").strip():
                    last_reasoning_message = str(event.message or "").strip()
                yield to_sse(event)
        if not saw_assistant_token and last_reasoning_message:
            yield to_sse(sequencer.event("token", message=last_reasoning_message))
        yield to_sse(sequencer.event("done", message="Run complete"))
        store.finish_run(run_id, "complete")
    except Exception as exc:
        yield to_sse(sequencer.event("error", message=str(exc), data={"errorType": type(exc).__name__}))
        store.finish_run(run_id, "error")
    finally:
        INTERRUPT_BROKER.clear_run(run_id)
