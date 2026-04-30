"""Runtime configuration for the local workbench."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_TOKEN = "dev-local-token"
DEFAULT_MODEL_ALLOWLIST = (
    "mock:deterministic",
    "openai:accounts/fireworks/models/qwen3p6-plus",
    "openai:accounts/fireworks/models/kimi-k2-thinking",
    "openai:accounts/fireworks/models/glm-4p7",
)


def _split_paths(value: str | None, fallback: Path) -> tuple[Path, ...]:
    if not value:
        return (fallback.resolve(),)
    return tuple(Path(item).expanduser().resolve() for item in value.split(os.pathsep) if item.strip())


def _split_csv(value: str | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return fallback
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _ollama_models() -> tuple[str, ...]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=0.2) as response:
            if response.status >= 500:
                return ()
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return ()
    models: list[str] = []
    for item in payload.get("models", []):
        name = str(item.get("model") or item.get("name") or "")
        if not name:
            continue
        families = " ".join(str(value).lower() for value in item.get("details", {}).get("families", []) or [])
        family = str(item.get("details", {}).get("family", "")).lower()
        if "embed" in name.lower() or "bert" in family or "bert" in families:
            continue
        models.append(f"ollama:{name}")
        if name.endswith(":latest"):
            models.append(f"ollama:{name.removesuffix(':latest')}")
    return tuple(dict.fromkeys(models))


def _default_model() -> str:
    return os.getenv("WORKBENCH_DEFAULT_MODEL", "openai:accounts/fireworks/models/qwen3p6-plus")


@dataclass(frozen=True)
class Settings:
    """Settings loaded from the process environment."""

    token: str
    allowed_roots: tuple[Path, ...]
    workspace_root: Path
    data_dir: Path
    default_model: str
    model_allowlist: tuple[str, ...]
    cors_origins: tuple[str, ...]
    remote_sandbox_url: str | None
    remote_sandbox_token: str | None
    max_file_bytes: int = 1_000_000
    max_tree_entries: int = 2_000
    command_timeout_seconds: int = 120
    command_output_bytes: int = 80_000

    @property
    def remote_sandbox_enabled(self) -> bool:
        return bool(self.remote_sandbox_url and self.remote_sandbox_token)

    def to_public_dict(self) -> dict:
        return {
            "defaultModel": self.default_model,
            "models": [{"value": model, "name": model} for model in self.model_allowlist],
            "modes": [
                {"id": "ask_before_edits", "name": "Ask before edits"},
                {"id": "accept_edits", "name": "Accept edits"},
                {"id": "accept_everything", "name": "Accept everything"},
            ],
            "workspaceModes": [
                {"id": "local", "name": "Scoped local workspace", "enabled": True},
                {"id": "uploaded", "name": "Uploaded files", "enabled": True},
                {
                    "id": "remote_sandbox",
                    "name": "Remote sandbox",
                    "enabled": self.remote_sandbox_enabled,
                },
            ],
            "allowedRoots": [str(path) for path in self.allowed_roots],
            "workspaceRoot": str(self.workspace_root),
            "currentWorkingDirectory": str(Path.cwd()),
            "tokenRequired": True,
        }

    def dump_json(self) -> str:
        return json.dumps(self.to_public_dict(), sort_keys=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    data_dir = Path(os.getenv("WORKBENCH_DATA_DIR", ".data")).expanduser().resolve()
    workspace_root = Path(os.getenv("WORKBENCH_WORKSPACE_ROOT", "workspaces")).expanduser().resolve()
    configured_roots = os.getenv("WORKBENCH_ALLOWED_ROOTS")
    discovered_ollama_models = _ollama_models()
    model_allowlist = _split_csv(
        os.getenv("WORKBENCH_MODEL_ALLOWLIST"),
        (*DEFAULT_MODEL_ALLOWLIST, *discovered_ollama_models),
    )
    default_model = _default_model()
    if default_model not in model_allowlist:
        model_allowlist = (default_model, *model_allowlist)
    return Settings(
        token=os.getenv("WORKBENCH_TOKEN", DEFAULT_TOKEN),
        allowed_roots=_split_paths(configured_roots, workspace_root),
        workspace_root=workspace_root,
        data_dir=data_dir,
        default_model=default_model,
        model_allowlist=model_allowlist,
        cors_origins=_split_csv(
            os.getenv("WORKBENCH_CORS_ORIGINS"),
            ("http://127.0.0.1:5175", "http://localhost:5175", "http://127.0.0.1:5173", "http://localhost:5173"),
        ),
        remote_sandbox_url=os.getenv("WORKBENCH_REMOTE_SANDBOX_URL") or None,
        remote_sandbox_token=os.getenv("WORKBENCH_REMOTE_SANDBOX_TOKEN") or None,
        max_file_bytes=int(os.getenv("WORKBENCH_MAX_FILE_BYTES", "1000000")),
        max_tree_entries=int(os.getenv("WORKBENCH_MAX_TREE_ENTRIES", "2000")),
        command_timeout_seconds=int(os.getenv("WORKBENCH_COMMAND_TIMEOUT_SECONDS", "120")),
        command_output_bytes=int(os.getenv("WORKBENCH_COMMAND_OUTPUT_BYTES", "80000")),
    )
