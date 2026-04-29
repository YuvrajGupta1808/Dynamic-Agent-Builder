"""Workspace filesystem and diff operations."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from ..core.config import Settings
from ..domain.models import DiffResponse, FileContentResponse, FileTreeNode, WorkspaceMode
from .security import ensure_allowed_root, resolve_workspace_path

IGNORED_DIRS = {".git", "node_modules", "dist", "coverage", ".data", ".venv", "venv", "__pycache__"}
TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class Workspace:
    session_id: str
    mode: WorkspaceMode
    root: Path
    remote_enabled: bool = False


class WorkspaceManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.workspace_root.mkdir(parents=True, exist_ok=True)

    def create(self, mode: WorkspaceMode, cwd: str | None, workspace_name: str | None = None) -> Workspace:
        session_id = uuid4().hex
        root = self.root_for(mode, session_id, cwd, workspace_name)
        root.mkdir(parents=True, exist_ok=True)
        return Workspace(
            session_id=session_id,
            mode=mode,
            root=root,
            remote_enabled=self.settings.remote_sandbox_enabled,
        )

    def root_for(self, mode: WorkspaceMode, session_id: str, cwd: str | None, workspace_name: str | None = None) -> Path:
        if mode == "local":
            if workspace_name:
                return self.workspace_path(workspace_name)
            requested = Path(cwd or Path.cwd())
            return ensure_allowed_root(requested, self.settings)
        if mode == "uploaded":
            return (self.settings.data_dir / "uploads" / session_id).resolve()
        return (self.settings.data_dir / "remote_sandbox" / session_id).resolve()

    def list_workspaces(self) -> list[dict[str, str]]:
        self.ensure_workspace("default")
        workspaces = []
        for path in sorted(self.settings.workspace_root.iterdir(), key=lambda item: item.name.lower()):
            if path.is_dir() and not path.name.startswith("."):
                workspaces.append({"name": path.name, "path": str(path.resolve())})
        return workspaces

    def ensure_workspace(self, name: str) -> Path:
        root = self.workspace_path(name)
        root.mkdir(parents=True, exist_ok=True)
        readme = root / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# {root.name}\n\nThis managed workspace is isolated from the main repository by default.\n",
                encoding="utf-8",
            )
        return root

    def workspace_path(self, name: str) -> Path:
        slug = sanitize_workspace_name(name)
        root = (self.settings.workspace_root / slug).resolve()
        ensure_allowed_root(root, self.settings)
        return root

    def tree(self, root: Path) -> FileTreeNode:
        entries_seen = 0

        def walk(path: Path, depth: int) -> FileTreeNode:
            nonlocal entries_seen
            relative = path.relative_to(root).as_posix() if path != root else ""
            node = FileTreeNode(
                name=path.name or root.name,
                path=relative,
                type="directory" if path.is_dir() else "file",
                size=path.stat().st_size if path.is_file() else None,
            )
            if not path.is_dir() or depth <= 0:
                return node
            children: list[FileTreeNode] = []
            try:
                candidates = sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
            except PermissionError:
                return node
            for child in candidates:
                if entries_seen >= self.settings.max_tree_entries:
                    break
                if child.name in IGNORED_DIRS:
                    continue
                try:
                    resolve_workspace_path(root, child.relative_to(root).as_posix(), must_exist=True)
                except HTTPException:
                    continue
                entries_seen += 1
                children.append(walk(child, depth - 1))
            node.children = children
            return node

        return walk(root, 5)

    def read_file(self, root: Path, path: str) -> FileContentResponse:
        resolved = resolve_workspace_path(root, path, must_exist=True)
        if not resolved.is_file():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path is not a file")
        if resolved.suffix and resolved.suffix.lower() not in TEXT_EXTENSIONS and resolved.stat().st_size > 64_000:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Binary or unsupported file")
        data = resolved.read_bytes()
        truncated = len(data) > self.settings.max_file_bytes
        data = data[: self.settings.max_file_bytes]
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="File is not UTF-8 text") from exc
        return FileContentResponse(path=path, content=content, truncated=truncated)

    def write_file(self, root: Path, path: str, content: str) -> FileContentResponse:
        resolved = resolve_workspace_path(root, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return FileContentResponse(path=path, content=content, truncated=False)

    async def save_uploads(self, root: Path, files: list[UploadFile]) -> list[str]:
        saved: list[str] = []
        for file in files:
            safe_name = Path(file.filename or "upload.txt").name
            target = resolve_workspace_path(root, safe_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = await file.read()
            target.write_bytes(content)
            saved.append(safe_name)
        return saved

    def diff(self, root: Path, path: str | None = None) -> DiffResponse:
        if not (root / ".git").exists():
            return DiffResponse(diff="", changedFiles=[])
        command = ["git", "-C", str(root), "diff", "--"]
        if path:
            resolved = resolve_workspace_path(root, path)
            command.append(resolved.relative_to(root).as_posix())
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
        status_result = subprocess.run(
            ["git", "-C", str(root), "status", "--short"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        changed = []
        for line in status_result.stdout.splitlines():
            if len(line) > 3:
                changed.append(line[3:])
        return DiffResponse(diff=result.stdout[: self.settings.command_output_bytes], changedFiles=changed)


def create_uploaded_seed(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text("# Uploaded Workspace\n\nAdd files using the upload endpoint or UI.\n", encoding="utf-8")


def sanitize_workspace_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip(".-")
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace name is required")
    if cleaned in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace name")
    return cleaned[:80]
