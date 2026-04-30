"""Security and authorization helpers for localhost-only operation."""

from __future__ import annotations

import fnmatch
import hmac
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import jwt
from fastapi import Header, HTTPException, Request, status
from jwt import PyJWKClient

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

logger = logging.getLogger(__name__)

_jwk_clients: dict[str, PyJWKClient] = {}


def _jwks_client(url: str) -> PyJWKClient:
    if url not in _jwk_clients:
        _jwk_clients[url] = PyJWKClient(url)
    return _jwk_clients[url]


@dataclass(frozen=True)
class AuthContext:
    """Authenticated caller identity after Bearer verification."""

    user_id: str
    source: Literal["token", "clerk"]


def decode_clerk_jwt(token: str, settings: Settings) -> dict[str, Any]:
    if not settings.clerk_jwks_url:
        raise ValueError("Clerk JWKS URL is not configured")
    client = _jwks_client(settings.clerk_jwks_url)
    signing_key = client.get_signing_key_from_jwt(token)
    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256", "ES256"],
        "options": {"verify_aud": False},
    }
    if settings.clerk_issuer:
        decode_kwargs["issuer"] = settings.clerk_issuer
    return jwt.decode(token, signing_key.key, **decode_kwargs)


def authenticate_request(authorization: str | None, settings: Settings) -> AuthContext:
    """Validate Authorization header.

    When Clerk is configured, legacy local token auth is disabled by default to prevent
    cross-user workspace sharing under the `_local` namespace.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw_token = authorization.removeprefix("Bearer ").strip()
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expected = f"Bearer {settings.token}"
    allow_legacy = (not settings.clerk_jwks_url) or settings.allow_legacy_token_with_clerk
    if allow_legacy and authorization and hmac.compare_digest(authorization, expected):
        return AuthContext(user_id=_sanitize_principal(settings.local_user_namespace), source="token")

    if settings.clerk_jwks_url:
        try:
            payload = decode_clerk_jwt(raw_token, settings)
            sub = payload.get("sub")
            if isinstance(sub, str) and sub.strip():
                return AuthContext(user_id=_sanitize_principal(sub), source="clerk")
        except jwt.exceptions.PyJWTError as exc:
            logger.debug("Clerk JWT verification failed: %s", exc)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _sanitize_principal(value: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip(".").strip("-")
    return cleaned[:120] if cleaned else "_user"


def get_auth_context(request: Request) -> AuthContext:
    ctx = getattr(request.state, "auth_context", None)
    if not isinstance(ctx, AuthContext):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ctx


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Backward-compatible dependency; prefer middleware + get_auth_context."""
    authenticate_request(authorization, get_settings())


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
