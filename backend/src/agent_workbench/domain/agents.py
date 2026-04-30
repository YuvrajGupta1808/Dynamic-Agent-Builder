"""Agent construction for HTTP streaming."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from ..infra.security import redact_env
from .fireworks_openai import FireworksReasoningChatOpenAI
from .models import SessionMode, WorkspaceMode

try:  # Optional: the app runs in mock mode without these packages.
    from deepagents import FilesystemPermission, create_deep_agent
    from deepagents.backends import CompositeBackend, LocalShellBackend, StateBackend, StoreBackend
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - exercised in environments without deepagents
    FilesystemPermission = None  # type: ignore[assignment]
    create_deep_agent = None  # type: ignore[assignment]
    CompositeBackend = None  # type: ignore[assignment]
    LocalShellBackend = None  # type: ignore[assignment]
    StateBackend = None  # type: ignore[assignment]
    StoreBackend = None  # type: ignore[assignment]
    ChatOpenAI = None  # type: ignore[assignment]

try:
    from tavily import TavilyClient
except Exception:  # pragma: no cover - optional dependency
    TavilyClient = None  # type: ignore[assignment]


SYSTEM_PROMPT = """You are a production coding agent running in a local workbench.
Work carefully inside the configured workspace, maintain a concise todo list, stream meaningful progress, and verify changes with focused tests.
Never read or write secret files. Ask for approval before shell commands when the current session mode requires it.
Prefer small, reviewable edits and explain tradeoffs when a task has safety or deployment implications.
If the `quick_search` tool is available, use it for fast real-time web lookups when requests depend on current external information.

Filesystem layout (virtual paths):
- The default route is the workspace. Write workspace files using bare relative paths like `fibonacci_cli.py` or `src/util.py`. Absolute virtual paths like `/fibonacci_cli.py` resolve under the workspace root.
- Reserved virtual namespaces — never use them for workspace files:
  - `/memories/` cross-thread agent memory store (persistent notes, not workspace files)
  - `/skills/` reusable skill specs (not workspace files)
  - `/policies/` shared compliance and policy docs (read-only)
  - `/conversation_history/` ephemeral run state
- Never use host-absolute paths (for example `/Users/...`, `/etc/...`, `/tmp/...`) for `read_file`, `write_file`, or `edit_file`. They will be rejected.
- Shell commands (`execute`) run with `cwd` already set to the workspace; reference workspace files using relative paths and avoid absolute host paths unless strictly required.

Realtime data policy:
- If a user asks for "current", "latest", "today", "right now", live prices, market moves, breaking news, or time-sensitive facts, call `quick_search` before answering.
- Do not claim you lack real-time access when `quick_search` is available.
- Summarize results with source-aware caveats when data may be delayed."""

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

    from ..infra.deep_agent_resources import get_checkpointer, get_langgraph_store

    resolved_checkpointer = checkpointer if checkpointer is not None else get_checkpointer()
    resolved_store = store if store is not None else get_langgraph_store()

    shell_backend = LocalShellBackend(
        root_dir=str(context.cwd),
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

    kwargs: dict[str, Any] = {
        "model": model,
        "system_prompt": SYSTEM_PROMPT,
        "backend": backend,
        "interrupt_on": get_interrupt_config(context.mode),
        "subagents": SUBAGENTS,
        "memory": [
            "/memories/WORKBENCH.md",
            "/policies/compliance.md",
        ],
        "skills": ["/skills/"],
        "store": resolved_store,
        "checkpointer": resolved_checkpointer,
    }
    quick_search_tool = _quick_search_tool()
    if quick_search_tool is not None:
        kwargs["tools"] = [quick_search_tool]
    # Deep Agents 0.5.x permission middleware does not yet support command-capable
    # backends. Keep shell safety on the backend boundary through workspace root
    # scoping, env redaction, and interrupt_on execute approvals.
    if os.getenv("WORKBENCH_ENABLE_DEEPAGENTS_PERMISSIONS") == "true":
        kwargs["permissions"] = _permissions()
    return create_deep_agent(**kwargs)
