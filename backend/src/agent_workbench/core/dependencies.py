"""FastAPI dependency injection providers."""

from __future__ import annotations

from functools import lru_cache

from ..infra.session_store import SessionStore
from ..infra.workspace import WorkspaceManager
from .config import get_settings


@lru_cache(maxsize=1)
def get_store() -> SessionStore:
    return SessionStore(get_settings().data_dir)


@lru_cache(maxsize=1)
def get_workspace_manager() -> WorkspaceManager:
    return WorkspaceManager(get_settings())
