"""Workspace filesystem and diff operations."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from ..core.config import Settings
from ..domain.models import DiffResponse, FileContentResponse, FileTreeNode, WorkspaceHealth, WorkspaceMode
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
ALLOWED_TOP_LEVEL_FILES = {"README.md"}
RECOVERABLE_TOP_LEVEL_FILES = {"guild.json"}
RECOVERABLE_TOP_LEVEL_DIRS = {"large_tool_results"}


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

    def create(
        self,
        mode: WorkspaceMode,
        cwd: str | None,
        workspace_name: str | None = None,
        *,
        user_id: str | None = None,
    ) -> Workspace:
        session_id = uuid4().hex
        root = self.root_for(mode, session_id, cwd, workspace_name, user_id=user_id)
        root.mkdir(parents=True, exist_ok=True)
        if mode == "local":
            self.ensure_contract(root)
        return Workspace(
            session_id=session_id,
            mode=mode,
            root=root,
            remote_enabled=self.settings.remote_sandbox_enabled,
        )

    def root_for(
        self,
        mode: WorkspaceMode,
        session_id: str,
        cwd: str | None,
        workspace_name: str | None = None,
        *,
        user_id: str | None = None,
    ) -> Path:
        if mode == "local":
            if not workspace_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="workspace is required for local workspace mode",
                )
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Workspace creation requires authenticated user context",
                )
            return self.workspace_path(user_id, workspace_name)
        if mode == "uploaded":
            return (self.settings.data_dir / "uploads" / session_id).resolve()
        return (self.settings.data_dir / "remote_sandbox" / session_id).resolve()

    def list_workspaces(self, user_id: str) -> list[dict[str, str]]:
        base = self.user_workspace_root(user_id)
        if not base.is_dir():
            return []
        workspaces = []
        for path in sorted(base.iterdir(), key=lambda item: item.name.lower()):
            if path.is_dir() and not path.name.startswith("."):
                workspaces.append({"name": path.name, "path": str(path.resolve())})
        return workspaces

    def user_workspace_root(self, user_id: str) -> Path:
        ns = sanitize_user_namespace(user_id)
        root = (self.settings.workspace_root / ns).resolve()
        ensure_allowed_root(root, self.settings)
        return root

    def workspace_path(self, user_id: str, name: str) -> Path:
        base = self.user_workspace_root(user_id)
        slug = sanitize_workspace_name(name)
        resolved = (base / slug).resolve()
        ensure_allowed_root(resolved, self.settings)
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace path") from exc
        return resolved

    def ensure_workspace(self, user_id: str, name: str) -> Path:
        root = self.workspace_path(user_id, name)
        root.mkdir(parents=True, exist_ok=True)
        self.ensure_contract(root)
        return root

    @property
    def canonical_agents_root(self) -> str:
        return self.settings.workspace_agents_root

    def agents_root(self, root: Path) -> Path:
        return root / self.settings.workspace_agents_root

    def ensure_contract(self, root: Path) -> None:
        agents_root = self.agents_root(root)
        agents_root.mkdir(parents=True, exist_ok=True)
        if self.settings.workspace_seed_readme:
            self._ensure_workspace_readmes(root, agents_root)
        self.validate_workspace_layout(root)

    def _ensure_workspace_readmes(self, root: Path, agents_root: Path) -> None:
        workspace_readme = root / "README.md"
        if not workspace_readme.exists():
            workspace_readme.write_text(
                (
                    f"# {root.name}\n\n"
                    "Guild builder workspace.\n\n"
                    "Workspace contract:\n"
                    f"- Root-level agent code lives under `{self.settings.workspace_agents_root}/<agent-name>/...`\n"
                    "- Keep this README updated with the operator-facing build and validation flow.\n"
                    "- Extra top-level artifacts are opt-in only.\n"
                ),
                encoding="utf-8",
            )

        agents_readme = agents_root / "README.md"
        if not agents_readme.exists():
            agents_readme.write_text(
                (
                    "# Agents\n\n"
                    "This directory contains Guild agents.\n\n"
                    "Rules:\n"
                    "- Each agent must live in its own subdirectory.\n"
                    "- Generated agent code and prompts stay within that agent directory.\n"
                    "- Keep this README updated when the agents layout or conventions change.\n"
                ),
                encoding="utf-8",
            )

    def validate_workspace_layout(self, root: Path) -> None:
        if not self._uses_local_workspace_contract(root):
            return
        health = self.workspace_health(root)
        if health.status == "invalid":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=health.model_dump(mode="json", by_alias=True))

    def _uses_local_workspace_contract(self, root: Path) -> bool:
        try:
            root.resolve().relative_to(self.settings.workspace_root.resolve())
        except ValueError:
            return False
        return True

    def workspace_health(self, root: Path) -> WorkspaceHealth:
        allowed_entries = [f"{self.settings.workspace_agents_root}/", "*.md"]
        if not root.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        if not self._uses_local_workspace_contract(root):
            return WorkspaceHealth(
                name=root.name,
                path=str(root.resolve()),
                status="valid",
                allowedTopLevelEntries=allowed_entries,
                message="Workspace is outside the managed local workspace root.",
            )

        invalid_entries: list[str] = []
        recoverable_entries: list[str] = []
        blocking_entries: list[str] = []
        allowed_dirs = {self.settings.workspace_agents_root}
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                if child.name in allowed_dirs:
                    continue
                entry = child.name + "/"
                invalid_entries.append(entry)
                if child.name in RECOVERABLE_TOP_LEVEL_DIRS:
                    recoverable_entries.append(entry)
                else:
                    blocking_entries.append(entry)
                continue
            if self._is_allowed_top_level_file(child):
                continue
            entry = child.name
            invalid_entries.append(entry)
            if child.name in RECOVERABLE_TOP_LEVEL_FILES:
                recoverable_entries.append(entry)
            else:
                blocking_entries.append(entry)

        if not invalid_entries:
            return WorkspaceHealth(
                name=root.name,
                path=str(root.resolve()),
                status="valid",
                allowedTopLevelEntries=allowed_entries,
                message="Workspace contract is valid.",
            )

        recoverable = len(blocking_entries) == 0
        return WorkspaceHealth(
            name=root.name,
            path=str(root.resolve()),
            status="invalid",
            recoverable=recoverable,
            repairAvailable=recoverable,
            invalidEntries=invalid_entries,
            recoverableEntries=recoverable_entries,
            blockingEntries=blocking_entries,
            allowedTopLevelEntries=allowed_entries,
            message=(
                "Workspace layout violation. Allowed top-level entries: "
                f"{', '.join(allowed_entries)}. "
                f"Disallowed entries: {', '.join(invalid_entries)}"
            ),
        )

    def _is_allowed_top_level_file(self, path: Path) -> bool:
        return path.name in ALLOWED_TOP_LEVEL_FILES or path.suffix.lower() == ".md"

    def repair_workspace(self, root: Path) -> WorkspaceHealth:
        health = self.workspace_health(root)
        if health.status == "valid":
            return health
        if not health.recoverable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=health.model_dump(mode="json", by_alias=True),
            )

        repaired_entries: list[str] = []
        quarantine_root = self._repair_target_root(root)
        quarantine_root.mkdir(parents=True, exist_ok=True)
        for entry in health.recoverable_entries:
            source = root / entry.removesuffix("/")
            if not source.exists():
                continue
            target = quarantine_root / source.name
            if target.exists():
                timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
                target = quarantine_root / f"{source.name}.{timestamp}"
            source.rename(target)
            repaired_entries.append(entry)

        self.ensure_contract(root)
        updated = self.workspace_health(root)
        return updated.model_copy(
            update={
                "repaired_entries": repaired_entries,
                "repair_available": updated.repair_available,
                "message": "Workspace repaired successfully." if updated.status == "valid" else updated.message,
            }
        )

    def _repair_target_root(self, root: Path) -> Path:
        return self.settings.data_dir / "workspace_repairs" / sanitize_workspace_name(root.name)

    def tree(self, root: Path) -> FileTreeNode:
        self.validate_workspace_layout(root)
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
        self.validate_workspace_layout(root)
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
        self.validate_workspace_layout(root)
        resolved = resolve_workspace_path(root, path)
        relative = resolved.relative_to(root).as_posix()
        if not self._is_allowed_workspace_write(relative):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Writes are restricted to top-level Markdown files and files under "
                    f"`{self.settings.workspace_agents_root}/<agent-name>/...`."
                ),
            )
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return FileContentResponse(path=path, content=content, truncated=False)

    async def save_uploads(self, root: Path, files: list[UploadFile]) -> list[str]:
        self.validate_workspace_layout(root)
        saved: list[str] = []
        for file in files:
            safe_name = Path(file.filename or "upload.txt").name
            target = resolve_workspace_path(root, safe_name)
            if self._uses_local_workspace_contract(root):
                relative = target.relative_to(root).as_posix()
                if not self._is_allowed_workspace_write(relative):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            "Uploads are restricted to top-level Markdown files and files under "
                            f"`{self.settings.workspace_agents_root}/<agent-name>/...`."
                        ),
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            content = await file.read()
            target.write_bytes(content)
            saved.append(safe_name)
        return saved

    def _is_allowed_workspace_write(self, relative: str) -> bool:
        if relative.startswith(f"{self.settings.workspace_agents_root}/"):
            return True
        if "/" in relative:
            return False
        return Path(relative).suffix.lower() == ".md"

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


def sanitize_user_namespace(user_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", user_id.strip()).strip(".").strip("-")
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user identifier")
    return cleaned[:120]


def sanitize_workspace_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip(".").strip("-")
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace name is required")
    if cleaned in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace name")
    return cleaned[:80]
