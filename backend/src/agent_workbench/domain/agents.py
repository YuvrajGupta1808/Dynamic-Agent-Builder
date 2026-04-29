"""Agent construction for HTTP streaming."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..infra.security import redact_env
from .models import SessionMode, WorkspaceMode

try:  # Optional: the app runs in mock mode without these packages.
    from deepagents import FilesystemPermission, create_deep_agent
    from deepagents.backends import CompositeBackend, LocalShellBackend, StateBackend
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - exercised in environments without deepagents
    FilesystemPermission = None  # type: ignore[assignment]
    create_deep_agent = None  # type: ignore[assignment]
    CompositeBackend = None  # type: ignore[assignment]
    LocalShellBackend = None  # type: ignore[assignment]
    StateBackend = None  # type: ignore[assignment]
    ChatOpenAI = None  # type: ignore[assignment]
    MemorySaver = None  # type: ignore[assignment]


SYSTEM_PROMPT = """You are a production coding agent running in a local workbench.
Work carefully inside the configured workspace, maintain a concise todo list, stream meaningful progress, and verify changes with focused tests.
Never read or write secret files. Ask for approval before shell commands when the current session mode requires it.
Prefer small, reviewable edits and explain tradeoffs when a task has safety or deployment implications."""

SUBAGENTS: list[dict[str, str]] = [
    {
        "name": "explorer",
        "description": "Read-only codebase analysis and architecture discovery.",
        "system_prompt": "Inspect the repository and report concrete findings with file paths. Do not edit files.",
    },
    {
        "name": "implementer",
        "description": "Scoped implementation worker for well-defined file changes.",
        "system_prompt": "Make focused code changes only within the requested scope and summarize changed files.",
    },
    {
        "name": "reviewer",
        "description": "Read-only review for bugs, regressions, and missing tests.",
        "system_prompt": "Review the current diff for correctness risks. Prioritize actionable findings.",
    },
    {
        "name": "test_runner",
        "description": "Runs approved commands and interprets test/build output.",
        "system_prompt": "Run only approved commands, keep output concise, and identify the next fix.",
    },
]


def get_interrupt_config(mode_id: SessionMode) -> dict[str, Any]:
    mode_to_interrupt: dict[str, dict[str, Any]] = {
        "ask_before_edits": {
            "edit_file": {"allowed_decisions": ["approve", "reject"]},
            "write_file": {"allowed_decisions": ["approve", "reject"]},
            "write_todos": {"allowed_decisions": ["approve", "reject"]},
            "execute": {"allowed_decisions": ["approve", "reject"]},
        },
        "accept_edits": {
            "execute": {"allowed_decisions": ["approve", "reject"]},
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
            "ns": ("tools:explorer",),
            "data": {
                "event": "subagent",
                "name": "explorer",
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
            "ns": ("tools:explorer",),
            "data": {"event": "subagent", "name": "explorer", "status": "completed", "summary": "Workspace scan complete."},
        }


def _permissions() -> list[Any]:
    if FilesystemPermission is None:
        return []
    return [
        FilesystemPermission(operations=["read", "write"], paths=["/workspace/.env", "/workspace/.env.*"], mode="deny"),
        FilesystemPermission(operations=["read", "write"], paths=["/workspace/**"], mode="allow"),
        FilesystemPermission(operations=["read", "write"], paths=["/memories/**"], mode="allow"),
        FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
    ]


def build_agent(context: AgentSessionContext) -> Any:
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

    ephemeral_backend = StateBackend()
    shell_backend = LocalShellBackend(
        root_dir=str(context.cwd),
        inherit_env=True,
        env=redact_env(os.environ.copy()),
    )
    backend = CompositeBackend(
        default=shell_backend,
        routes={
            "/memories/": StateBackend(),
            "/conversation_history/": ephemeral_backend,
        },
    )
    checkpointer = MemorySaver() if MemorySaver is not None else None
    model: Any = context.model
    if context.model.startswith("openai:") and ChatOpenAI is not None:
        # Use an explicit OpenAI-compatible client to bound retries/timeouts and
        # avoid indefinite hangs in upstream model calls.
        openai_model = context.model.split("openai:", 1)[1]
        chat_kwargs: dict[str, Any] = {
            "model": openai_model,
            "timeout": float(max(context.command_timeout_seconds, 30)),
            "max_retries": 1,
        }
        if "accounts/fireworks/models/" in context.model:
            chat_kwargs["base_url"] = os.getenv("OPENAI_BASE_URL", "https://api.fireworks.ai/inference/v1")
        # Fireworks Qwen 3.6 Plus emits reasoning_content natively, but
        # langchain-openai chat-completions parsing may drop it. Responses API
        # with responses/v1 output keeps reasoning blocks available for stream
        # normalization and UI rendering.
        if "accounts/fireworks/models/qwen3p6-plus" in context.model:
            chat_kwargs["use_responses_api"] = True
            chat_kwargs["output_version"] = "responses/v1"
            chat_kwargs["reasoning_effort"] = "low"
        model = ChatOpenAI(**chat_kwargs)

    kwargs: dict[str, Any] = {
        "model": model,
        "system_prompt": SYSTEM_PROMPT,
        "backend": backend,
        "interrupt_on": get_interrupt_config(context.mode),
        "subagents": SUBAGENTS,
    }
    # Deep Agents 0.5.x permission middleware does not yet support command-capable
    # backends. Keep shell safety on the backend boundary through workspace root
    # scoping, env redaction, and interrupt_on execute approvals.
    if os.getenv("WORKBENCH_ENABLE_DEEPAGENTS_PERMISSIONS") == "true":
        kwargs["permissions"] = _permissions()
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    return create_deep_agent(**kwargs)
