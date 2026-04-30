"""Process-wide LangGraph checkpointer and Deep Agents store (memory doc alignment)."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.store.memory import InMemoryStore

_lock = Lock()
_checkpointer: Any | None = None
_store: Any | None = None


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
"""
            ),
        )


def ensure_session_store_seeded(store: Any, session_id: str) -> None:
    """Per-session long-term memory and skill seeds (namespaced store); idempotent."""
    from deepagents.backends.utils import create_file_data

    ns = (session_id,)

    mem_key = "/memories/WORKBENCH.md"
    if store.get(ns, mem_key) is None:
        store.put(
            ns,
            mem_key,
            create_file_data(
                """## Session memory
Use this file for preferences and durable facts for this conversation session.
You may update it when the user asks you to remember something.
"""
            ),
        )

    skill_key = "/skills/workbench-hint/SKILL.md"
    if store.get(ns, skill_key) is None:
        store.put(
            ns,
            skill_key,
            create_file_data(
                """---
name: workbench-hint
description: Reminds the agent to use the workbench workspace root for file tools.
---

# workbench-hint

Prefer reading and editing files under the configured workspace path. Use memory files under `/memories/` for durable notes across turns.
"""
            ),
        )
