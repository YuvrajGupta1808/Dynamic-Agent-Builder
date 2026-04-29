from pathlib import Path

import pytest
from fastapi import HTTPException

from agent_workbench.core.config import Settings
from agent_workbench.infra.security import ensure_allowed_root, resolve_workspace_path, validate_model


def settings(tmp_path: Path) -> Settings:
    return Settings(
        token="test-token",
        allowed_roots=(tmp_path,),
        workspace_root=tmp_path,
        data_dir=tmp_path / ".data",
        default_model="mock:deterministic",
        model_allowlist=("mock:deterministic",),
        cors_origins=("http://127.0.0.1:5173",),
        remote_sandbox_url=None,
        remote_sandbox_token=None,
    )


def test_allowed_root_accepts_child(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    assert ensure_allowed_root(root, settings(tmp_path)) == root.resolve()


def test_allowed_root_rejects_outside(tmp_path: Path) -> None:
    with pytest.raises(HTTPException):
        ensure_allowed_root(Path("/tmp"), settings(tmp_path / "allowed"))


def test_resolve_workspace_path_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(HTTPException):
        resolve_workspace_path(root, "../outside.txt")


def test_resolve_workspace_path_rejects_env_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(HTTPException):
        resolve_workspace_path(root, ".env")


def test_validate_model_enforces_allowlist(tmp_path: Path) -> None:
    active = settings(tmp_path)
    assert validate_model("mock:deterministic", active) == "mock:deterministic"
    with pytest.raises(HTTPException):
        validate_model("openai:not-allowed", active)
