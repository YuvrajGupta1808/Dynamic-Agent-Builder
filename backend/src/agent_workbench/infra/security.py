"""Security and authorization helpers for localhost-only operation."""

from __future__ import annotations

import fnmatch
import hmac
import os
from pathlib import Path

from fastapi import Header, HTTPException, status

from ..core.config import Settings, get_settings

DENIED_FILE_PATTERNS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "**/*secret*",
    "**/*token*",
    "**/*credential*",
    "**/id_rsa",
    "**/id_ed25519",
)

SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def require_auth(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = f"Bearer {settings.token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def validate_model(model: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    if model not in active_settings.model_allowlist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model is not allowlisted: {model}",
        )
    return model


def ensure_allowed_root(path: Path, settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    resolved = path.expanduser().resolve()
    for root in active_settings.allowed_roots:
        if resolved == root or root in resolved.parents:
            return resolved
    roots = ", ".join(str(root) for root in active_settings.allowed_roots)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Workspace root is outside WORKBENCH_ALLOWED_ROOTS: {roots}",
    )


def _is_denied_relative_path(relative_path: Path) -> bool:
    normalized = relative_path.as_posix()
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in DENIED_FILE_PATTERNS)


def resolve_workspace_path(root: Path, user_path: str | None, *, must_exist: bool = False) -> Path:
    raw = user_path or "."
    if raw.startswith("/"):
        raw = raw[1:]
    candidate = (root / raw).expanduser().resolve()
    try:
        relative = candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path escapes workspace") from exc
    if _is_denied_relative_path(relative):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Path is denied by local policy")
    if must_exist and not candidate.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Path not found")
    return candidate


def redact_env(env: dict[str, str] | None = None) -> dict[str, str]:
    source = dict(env or os.environ)
    redacted: dict[str, str] = {}
    for key, value in source.items():
        if any(marker in key.upper() for marker in SECRET_ENV_MARKERS):
            continue
        redacted[key] = value
    return redacted
