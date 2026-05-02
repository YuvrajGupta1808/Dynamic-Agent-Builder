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
from ..infra.command_policy import BlockedCommandError, GuildExecutionContext, evaluate_execute_request
from ..infra.deep_agent_resources import ensure_session_store_seeded, get_langgraph_store
from ..infra.session_store import SessionStore

MAX_RUN_MESSAGES = 64
MAX_MESSAGE_CHARS = 120_000


class InterruptDecisionBroker:
    """In-memory bridge between interrupt decisions API and active stream workers."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._pending: dict[tuple[str, str], dict[str, Any]] = {}
        self._decisions: dict[tuple[str, str], Any] = {}
        self._recent: dict[tuple[str, str, str], tuple[float, Any]] = {}

    def register(self, run_id: str, interrupt_id: str, *, tool: str = "", payload: dict[str, Any] | None = None) -> None:
        with self._cond:
            self._pending[(run_id, interrupt_id)] = {
                "tool": tool,
                "payload": dict(payload or {}),
            }
            self._cond.notify_all()

    def publish(self, run_id: str, interrupt_id: str, decision: Any) -> bool:
        with self._cond:
            key = (run_id, interrupt_id)
            pending = self._pending.get(key) or {}
            tool = str(pending.get("tool") or "")
            payload = pending.get("payload")
            if tool:
                fingerprint = self._fingerprint(run_id, tool, payload if isinstance(payload, dict) else {})
                self._recent[fingerprint] = (time.monotonic() + 30.0, decision)
            self._decisions[key] = decision
            self._cond.notify_all()
            return key in self._pending

    def reuse_recent_decision(self, run_id: str, tool: str, payload: dict[str, Any] | None) -> Any | None:
        key = self._fingerprint(run_id, tool, payload or {})
        with self._cond:
            recent = self._recent.get(key)
            if recent is None:
                return None
            expires_at, decision = recent
            if expires_at <= time.monotonic():
                self._recent.pop(key, None)
                return None
            return decision

    def wait_for(self, run_id: str, interrupt_id: str, timeout_seconds: float) -> Any | None:
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
            recent_keys = [key for key in self._recent if key[0] == run_id]
            for key in recent_keys:
                self._recent.pop(key, None)

    @staticmethod
    def _fingerprint(run_id: str, tool: str, payload: dict[str, Any]) -> tuple[str, str, str]:
        normalized = dict(payload)
        normalized.pop("_rawInterrupt", None)
        payload_key = json.dumps(_safe_data(normalized), sort_keys=True, separators=(",", ":"))
        return (run_id, tool, payload_key)


INTERRUPT_BROKER = InterruptDecisionBroker()


def submit_interrupt_decision(run_id: str, interrupt_id: str, decision: Any) -> bool:
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
            "do not call pwd or use host-absolute paths to write workspace files. "
            "Track three scopes explicitly: local builder workspace `/`, local agent repo `/agents/<agent-name>/`, "
            "and selected remote Guild workspace metadata. Never run `guild agent init` at `/`; run it only inside "
            "`/agents/<agent-name>/` or with `--directory agents/<agent-name>`."
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


def _specialist_from_source(source: str) -> str | None:
    if not source:
        return None
    if source.startswith("tools:"):
        candidate = source.split(":", 1)[1]
        return candidate or None
    return source if source != "main" else "main"


def _interrupt_specialist(source: str, current_specialist: str | None) -> str:
    explicit = (current_specialist or "").strip()
    if explicit:
        return explicit
    from_source = _specialist_from_source(source)
    return from_source or "main"


def _command_cwd_from_payload(payload: dict[str, Any], workspace_root: Path) -> Path:
    raw_cwd = payload.get("cwd")
    if isinstance(raw_cwd, str) and raw_cwd.strip():
        return Path(raw_cwd)
    return workspace_root


def _agent_name_from_mapping(mapping: Any) -> str | None:
    if not isinstance(mapping, dict):
        return None
    candidate = mapping.get("lc_agent_name") or mapping.get("agent_name")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


def _agent_name_from_token(token: Any) -> str | None:
    if isinstance(token, dict):
        for value in (
            token.get("metadata"),
            token.get("response_metadata"),
            token.get("additional_kwargs"),
        ):
            agent_name = _agent_name_from_mapping(value)
            if agent_name:
                return agent_name
        return None
    for attr in ("metadata", "response_metadata", "additional_kwargs"):
        agent_name = _agent_name_from_mapping(getattr(token, attr, None))
        if agent_name:
            return agent_name
    return None


def _source_for_message(ns: Any, token: Any, metadata: Any | None = None) -> str:
    metadata_agent = _agent_name_from_mapping(metadata)
    if metadata_agent:
        return metadata_agent
    token_agent = _agent_name_from_token(token)
    if token_agent:
        return token_agent
    return _source_from_ns(ns)


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


def _interrupt_payloads_to_requests(raw_interrupt: Any) -> list[dict[str, Any]]:
    # LangGraph interrupt objects often carry a `.value`; convert to plain data.
    interrupt_value = getattr(raw_interrupt, "value", raw_interrupt)
    if isinstance(interrupt_value, dict):
        review_configs_raw = interrupt_value.get("review_configs")
        review_config_map: dict[str, dict[str, Any]] = {}
        if isinstance(review_configs_raw, list):
            for review_config in review_configs_raw:
                if not isinstance(review_config, dict):
                    continue
                action_name = review_config.get("action_name")
                if isinstance(action_name, str) and action_name:
                    review_config_map[action_name] = review_config
        action_requests = interrupt_value.get("action_requests")
        if isinstance(action_requests, list) and action_requests:
            prepared: list[dict[str, Any]] = []
            for action_request in action_requests:
                if not isinstance(action_request, dict):
                    continue
                tool_name = str(action_request.get("name") or "execute")
                args = action_request.get("args")
                review_config = review_config_map.get(tool_name, {})
                raw_allowed_decisions = review_config.get("allowed_decisions")
                allowed_decisions = ["approve", "edit", "reject"]
                if isinstance(raw_allowed_decisions, list):
                    normalized = [str(item) for item in raw_allowed_decisions if str(item) in {"approve", "edit", "reject"}]
                    if normalized:
                        allowed_decisions = normalized
                if isinstance(args, dict):
                    payload = dict(args)
                else:
                    payload = {"rawArgs": _safe_data(args)}
                prepared.append(
                    {
                        "tool": tool_name,
                        "payload": payload,
                        "allowedDecisions": allowed_decisions,
                        "rawInterrupt": _safe_data(interrupt_value),
                    }
                )
            return prepared
        tool = str(interrupt_value.get("tool") or "execute")
        payload = interrupt_value.get("payload")
        if isinstance(payload, dict):
            return [{"tool": tool, "payload": payload, "allowedDecisions": ["approve", "reject"], "rawInterrupt": _safe_data(interrupt_value)}]
    return [{"tool": "execute", "payload": {"rawInterrupt": _safe_data(interrupt_value)}, "allowedDecisions": ["approve", "reject"], "rawInterrupt": _safe_data(interrupt_value)}]


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
        for request in _interrupt_payloads_to_requests(raw):
            tool = str(request.get("tool") or "execute")
            payload = dict(request.get("payload") or {})
            prepared.append(
                {
                    "interruptId": uuid4().hex,
                    "tool": tool,
                    "payload": payload,
                    "allowedDecisions": list(request.get("allowedDecisions") or ["approve", "reject"]),
                    "rawInterrupt": request.get("rawInterrupt"),
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
    workspace_root: Path | None = None,
    current_specialist: str | None = None,
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
            if tool == "execute" and workspace_root is not None:
                specialist = _interrupt_specialist(source, current_specialist)
                decision = evaluate_execute_request(
                    GuildExecutionContext(
                        specialist=specialist,
                        command=str(payload.get("command") or payload.get("cmd") or ""),
                        workspace_root=workspace_root,
                        current_cwd=_command_cwd_from_payload(payload, workspace_root),
                    )
                )
                if not decision.allowed:
                    INTERRUPT_BROKER.publish(
                        sequencer.run_id,
                        interrupt_id,
                        {"type": "reject", "message": decision.reason},
                    )
                    events.append(
                        sequencer.event(
                            "blocked_command",
                            source=decision.specialist,
                            message=decision.reason,
                            data=decision.as_event(),
                        )
                    )
                    continue
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
                allowedDecisions=list(pending.get("allowedDecisions") or ["approve", "reject"]),
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
        metadata = data[1] if len(data) > 1 else {}
        source = _source_for_message(ns, token, metadata)
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
            # Dual-stream runs deliver reasoning in both `messages` and `updates`.
            # When `emit_update_tokens` is False, prefer the canonical `updates`
            # branch to avoid duplicate thinking cards.
            if emit_update_tokens:
                events.append(
                    sequencer.event(
                        "thinking",
                        source=source,
                        message=thinking,
                        data={"metadata": metadata if isinstance(metadata, dict) else {}},
                    )
                )
        content = _message_content(token)
        if content and _token_type(token) != "tool":
            events.append(sequencer.event("token", source=source, message=content, data={"metadata": metadata if isinstance(metadata, dict) else {}}))
        elif _token_type(token) == "tool":
            events.append(sequencer.event("tool_call", source=source, message=str(content)[:500], data={"result": content}))
        return events

    if chunk_type == "updates":
        extracted = False
        update_payload = data if isinstance(data, dict) else {}
        for message in _iter_messages_from_update(update_payload):
            message_source = _source_for_message(ns, message)
            msg_type = _message_type(message)
            if msg_type not in {"ai", "assistant", "aimessage", "aimessagechunk"}:
                continue
            # Prefer complete reasoning summaries from update payloads to avoid
            # word-by-word stream chunks in the UI.
            reasoning = _message_thinking(message)
            tool_calls = _message_tool_calls(message)
            if reasoning:
                events.append(sequencer.event("thinking", source=message_source, message=reasoning))
                extracted = True
            for tool_call in tool_calls:
                if isinstance(tool_call, dict) and tool_call.get("name"):
                    events.append(
                        sequencer.event(
                            "tool_call",
                            source=message_source,
                            message=f"Tool call: {tool_call.get('name')}",
                            data={"name": tool_call.get("name"), "args": tool_call.get("args", {})},
                        )
                    )
                    extracted = True
            text = _message_content(message)
            if text and emit_update_tokens:
                events.append(sequencer.event("token", source=message_source, message=text))
                extracted = True
            # Some reasoning models finish with reasoning summaries and no
            # explicit text block. Promote that terminal reasoning to token so
            # the UI always has a final visible assistant response.
            elif emit_update_tokens and reasoning and not tool_calls:
                events.append(sequencer.event("token", source=message_source, message=reasoning))
                extracted = True
        if not extracted:
            events.append(sequencer.event("update", source=source, message="Graph update", data={"update": _safe_data(data)}))
        return events

    if chunk_type == "custom" and isinstance(data, dict):
        custom_event = data.get("event")
        if custom_event == "todo":
            events.append(sequencer.event("todo", source=source, message="Todo list updated", data={"items": data.get("items", [])}))
        elif custom_event == "subagent":
            subagent_source = str(data.get("name") or source)
            events.append(sequencer.event("subagent", source=subagent_source, message=data.get("summary"), data=data))
        elif custom_event == "tool_call":
            events.append(sequencer.event("tool_call", source=source, message=f"Tool call: {data.get('name')}", data=data))
        elif custom_event == "file_change":
            events.append(sequencer.event("file_change", source=source, message=data.get("summary"), data=data))
        elif custom_event == "blocked_command":
            specialist = str(data.get("specialist") or source)
            command = str(data.get("command") or "")
            events.append(
                sequencer.event(
                    "blocked_command",
                    source=specialist,
                    message=f"Blocked command: {command}".rstrip(),
                    data=data,
                )
            )
        elif custom_event == "approval_required":
            interrupt_id = str(data.get("interruptId") or uuid4().hex)
            approval = ApprovalRecord(
                runId=sequencer.run_id,
                interruptId=interrupt_id,
                tool=str(data.get("tool") or "unknown"),
                payload=dict(data.get("payload") or {}),
                allowedDecisions=list(data.get("allowedDecisions") or ["approve", "reject"]),
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


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name)
    try:
        value = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return max(value, minimum)


def _delegate_wait_state_from_event(event: StreamEvent) -> dict[str, str] | None:
    if event.type == "subagent":
        name = read_string_value(event.data.get("name")) or event.source or "specialist"
        status = read_string_value(event.data.get("status")) or "running"
        summary = read_string_value(event.data.get("summary")) or event.message or f"{name} is running"
        return {"name": name, "status": status, "summary": summary}
    if event.type != "tool_call":
        return None
    tool_name = read_string_value(event.data.get("name"))
    if tool_name not in {"task", "start_async_task"}:
        return None
    args = event.data.get("args")
    if not isinstance(args, dict):
        args = {}
    name = read_string_value(args.get("subagent_type")) or read_string_value(args.get("name")) or "specialist"
    summary = (
        read_string_value(args.get("description"))
        or read_string_value(args.get("task"))
        or read_string_value(args.get("prompt"))
        or f"{name} is running"
    )
    return {"name": name, "status": "running", "summary": summary}


def _delegate_wait_cleared_by_event(event: StreamEvent, active_delegate: dict[str, str] | None) -> bool:
    if active_delegate is None:
        return False
    delegate_name = active_delegate.get("name") or ""
    if event.type == "subagent":
        event_name = read_string_value(event.data.get("name")) or event.source
        status = (read_string_value(event.data.get("status")) or "").lower()
        if delegate_name and event_name == delegate_name and status in {"completed", "complete", "success", "error", "cancelled", "failed"}:
            return True
    if event.source == "main" and event.type in {"token", "thinking", "approval_required", "file_change", "todo"}:
        return True
    if event.type == "tool_call" and read_string_value(event.data.get("name")) not in {"task", "start_async_task"} and event.source == "main":
        return True
    return False


def read_string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


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
        ensure_session_store_seeded(get_langgraph_store(), session.id, Path(session.cwd))
        agent = build_agent(context)
        stream_messages = messages_for_agent_run(request, workspace_name=context.cwd.name)
        saw_assistant_token = False
        last_reasoning_message = ""
        chunk_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        queue_poll_seconds = _env_float("WORKBENCH_STREAM_QUEUE_POLL_SECONDS", 5.0, 0.05)
        inactivity_warning_seconds = _env_float("WORKBENCH_STREAM_IDLE_WARNING_SECONDS", 45.0, 0.05)
        stream_hard_timeout_seconds = max(
            _env_float(
                "WORKBENCH_STREAM_HARD_TIMEOUT_SECONDS",
                max(float(command_timeout_seconds), inactivity_warning_seconds + 30.0),
                inactivity_warning_seconds + 0.05,
            ),
            inactivity_warning_seconds + 0.05,
        )
        delegate_warning_seconds = _env_float(
            "WORKBENCH_STREAM_SUBAGENT_HEARTBEAT_SECONDS",
            inactivity_warning_seconds,
            0.05,
        )
        delegate_hard_timeout_seconds = max(
            _env_float(
                "WORKBENCH_STREAM_SUBAGENT_TIMEOUT_SECONDS",
                max(stream_hard_timeout_seconds * 1.5, 180.0),
                stream_hard_timeout_seconds,
            ),
            stream_hard_timeout_seconds,
        )
        started_at = time.monotonic()
        last_chunk_at = started_at
        next_idle_warning_at = started_at + inactivity_warning_seconds
        waiting_for_approval = threading.Event()
        updates_only_stream_mode = False
        active_delegate: dict[str, str] | None = None
        max_tool_calls_per_run = max(1, int(_env_float("WORKBENCH_STREAM_MAX_TOOL_CALLS", 1200.0, 1.0)))
        tool_call_count = 0

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
                    decided_interrupt_ids: set[str] = set()
                    decided_fingerprints: set[str] = set()
                    for chunk in chunks:
                        enriched_chunk, interrupts = _attach_interrupts_to_chunk(chunk)
                        for pending in interrupts:
                            if pending.get("autoApprove"):
                                continue
                            tool_name = str(pending.get("tool") or "")
                            payload = dict(pending.get("payload") or {})
                            fingerprint = f"{tool_name}|{json.dumps(payload, sort_keys=True, default=str)}"
                            if fingerprint in decided_fingerprints:
                                continue
                            interrupt_id = str(pending.get("interruptId") or "")
                            if not interrupt_id or interrupt_id in decided_interrupt_ids:
                                continue
                            INTERRUPT_BROKER.register(
                                run_id,
                                interrupt_id,
                                tool=tool_name,
                                payload=payload,
                            )
                        chunk_queue.put(("chunk", enriched_chunk))
                        if not interrupts:
                            continue
                        saw_interrupt = True
                        for pending in interrupts:
                            interrupt_id = str(pending.get("interruptId") or "")
                            if interrupt_id and interrupt_id in decided_interrupt_ids:
                                continue
                            tool_name = str(pending.get("tool") or "")
                            payload = dict(pending.get("payload") or {})
                            fingerprint = f"{tool_name}|{json.dumps(payload, sort_keys=True, default=str)}"
                            if fingerprint in decided_fingerprints:
                                if interrupt_id:
                                    decided_interrupt_ids.add(interrupt_id)
                                continue
                            if pending.get("autoApprove"):
                                interrupt_decisions.append({"type": "approve"})
                                decided_fingerprints.add(fingerprint)
                                if interrupt_id:
                                    decided_interrupt_ids.add(interrupt_id)
                                continue
                            reused_decision = INTERRUPT_BROKER.reuse_recent_decision(run_id, tool_name, payload)
                            if reused_decision is not None:
                                chunk_queue.put(
                                    (
                                        "chunk",
                                        {
                                            "type": "custom",
                                            "ns": (),
                                            "data": {
                                                "event": "update",
                                                "status": "reused_approval",
                                                "tool": tool_name,
                                                "message": f"Reused recent approval for {tool_name}",
                                            },
                                        },
                                    )
                                )
                                interrupt_decisions.append(reused_decision)
                                decided_fingerprints.add(fingerprint)
                                if interrupt_id:
                                    decided_interrupt_ids.add(interrupt_id)
                                continue
                            if not interrupt_id:
                                continue
                            waiting_for_approval.set()
                            decision = INTERRUPT_BROKER.wait_for(
                                run_id,
                                interrupt_id,
                                timeout_seconds=float(max(command_timeout_seconds, 30)),
                            )
                            waiting_for_approval.clear()
                            if decision is None:
                                raise TimeoutError(
                                    f"Timed out waiting for approval decision for interrupt {interrupt_id}."
                                )
                            if isinstance(decision, dict):
                                interrupt_decisions.append(decision)
                            elif decision == "approve":
                                interrupt_decisions.append({"type": "approve"})
                            else:
                                interrupt_decisions.append(
                                    {"type": "reject", "message": "User rejected this tool execution request."}
                                )
                            decided_fingerprints.add(fingerprint)
                            decided_interrupt_ids.add(interrupt_id)
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
                if waiting_for_approval.is_set():
                    if now >= next_idle_warning_at:
                        yield to_sse(
                            sequencer.event(
                                "update",
                                message="Waiting for approval",
                                data={"status": "waiting_for_approval", "idleSeconds": int(idle_seconds)},
                            )
                        )
                        next_idle_warning_at = now + inactivity_warning_seconds
                    continue
                if active_delegate and worker.is_alive():
                    if now >= next_idle_warning_at:
                        delegate_name = active_delegate.get("name") or "specialist"
                        delegate_summary = active_delegate.get("summary") or f"{delegate_name} is still running"
                        yield to_sse(
                            sequencer.event(
                                "subagent",
                                source=delegate_name,
                                message=delegate_summary,
                                data={
                                    "name": delegate_name,
                                    "status": active_delegate.get("status") or "running",
                                    "summary": delegate_summary,
                                    "waiting": True,
                                    "idleSeconds": int(idle_seconds),
                                    "elapsedSeconds": int(total_seconds),
                                },
                            )
                        )
                        next_idle_warning_at = now + delegate_warning_seconds
                    if total_seconds >= delegate_hard_timeout_seconds:
                        timeout_message = (
                            f"Subagent stalled: no stream events received for {int(idle_seconds)}s while waiting on "
                            f"{active_delegate.get('name') or 'a delegated task'}."
                        )
                        yield to_sse(
                            sequencer.event(
                                "error",
                                message=timeout_message,
                                data={
                                    "errorType": "SubagentStalledTimeout",
                                    "delegate": active_delegate.get("name"),
                                },
                            )
                        )
                        yield to_sse(sequencer.event("done", message="Run terminated after subagent stall timeout"))
                        store.finish_run(run_id, "error")
                        return
                    continue
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
                workspace_root=context.cwd,
                current_specialist=active_delegate["name"] if active_delegate is not None else None,
            ):
                cleared_delegate: dict[str, str] | None = None
                if event.type == "tool_call":
                    tool_call_count += 1
                    if tool_call_count > max_tool_calls_per_run:
                        yield to_sse(
                            sequencer.event(
                                "error",
                                message=(
                                    f"Run terminated after exceeding tool-call budget "
                                    f"({max_tool_calls_per_run})."
                                ),
                                data={
                                    "errorType": "ToolCallBudgetExceeded",
                                    "toolCalls": tool_call_count,
                                    "budget": max_tool_calls_per_run,
                                },
                            )
                        )
                        yield to_sse(sequencer.event("done", message="Run terminated after tool-call budget"))
                        store.finish_run(run_id, "error")
                        return
                if _delegate_wait_cleared_by_event(event, active_delegate):
                    cleared_delegate = dict(active_delegate) if active_delegate is not None else None
                    active_delegate = None
                delegate_state = _delegate_wait_state_from_event(event)
                if delegate_state is not None:
                    active_delegate = delegate_state
                    yield to_sse(
                        sequencer.event(
                            "subagent",
                            source=delegate_state.get("name") or "specialist",
                            message=delegate_state.get("summary") or "Delegated task started",
                            data={
                                "name": delegate_state.get("name") or "specialist",
                                "status": "started",
                                "summary": delegate_state.get("summary") or "Delegated task started",
                                "fromEvent": event.type,
                            },
                        )
                    )
                if (
                    event.source != "main"
                    and not str(event.source).startswith("tools:")
                    and event.type in {"token", "thinking", "tool_call"}
                ):
                    progress_message = read_string_value(event.message) or f"{event.source} is running"
                    yield to_sse(
                        sequencer.event(
                            "subagent",
                            source=event.source,
                            message=progress_message[:240],
                            data={
                                "name": event.source,
                                "status": "running",
                                "summary": progress_message[:240],
                                "fromEvent": event.type,
                            },
                        )
                    )
                if cleared_delegate is not None:
                    delegate_name = cleared_delegate.get("name") or "specialist"
                    delegate_summary = cleared_delegate.get("summary") or f"{delegate_name} completed"
                    yield to_sse(
                        sequencer.event(
                            "subagent",
                            source=delegate_name,
                            message=delegate_summary,
                            data={
                                "name": delegate_name,
                                "status": "completed",
                                "summary": delegate_summary,
                                "fromEvent": event.type,
                            },
                        )
                    )
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
        if isinstance(exc, BlockedCommandError):
            yield to_sse(
                sequencer.event(
                    "blocked_command",
                    source=exc.decision.specialist,
                    message=exc.decision.reason,
                    data=exc.decision.as_event(),
                )
            )
        yield to_sse(sequencer.event("error", message=str(exc), data={"errorType": type(exc).__name__}))
        store.finish_run(run_id, "error")
    finally:
        INTERRUPT_BROKER.clear_run(run_id)
