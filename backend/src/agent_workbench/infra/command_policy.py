"""Guild CLI specialist command policy."""

from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class BlockedCommandError(RuntimeError):
    def __init__(self, decision: "CommandPolicyDecision") -> None:
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class SpecialistCommandPolicy:
    specialist: str
    allowed_commands: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class CommandPolicyDecision:
    allowed: bool
    specialist: str
    command: str
    matched_rule: str | None
    reason: str

    def as_event(self) -> dict[str, Any]:
        return {
            "event": "blocked_command",
            "specialist": self.specialist,
            "command": self.command,
            "matchedRule": self.matched_rule,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GuildExecutionContext:
    specialist: str
    command: str
    workspace_root: Path
    current_cwd: Path | None = None


SPECIALIST_COMMAND_POLICIES: dict[str, SpecialistCommandPolicy] = {
    "decomposer": SpecialistCommandPolicy("decomposer", (), "No Guild CLI execution."),
    "template_selector": SpecialistCommandPolicy("template_selector", (), "No Guild CLI execution."),
    "workspace_initializer": SpecialistCommandPolicy(
        "workspace_initializer",
        (
            "guild workspace list",
            "guild workspace create",
            "guild workspace get",
            "guild workspace select",
            "guild workspace current",
            "guild workspace agent add",
            "guild workspace agent list",
            "guild workspace agent remove",
            "guild workspace context list",
            "guild workspace context get",
            "guild workspace context edit",
            "guild workspace context publish",
        ),
        "Workspace lifecycle only.",
    ),
    "agent_initializer": SpecialistCommandPolicy(
        "agent_initializer",
        (
            "guild auth status",
            "guild agent init",
            "guild agent test --ephemeral",
            "guild agent save",
        ),
        "Per-agent init/test/save only.",
    ),
    "cli_specialist": SpecialistCommandPolicy(
        "cli_specialist",
        (
            "guild auth status",
            "guild workspace list",
            "guild workspace create",
            "guild workspace get",
            "guild workspace select",
            "guild workspace current",
            "guild workspace agent add",
            "guild workspace agent list",
            "guild workspace agent remove",
            "guild workspace context list",
            "guild workspace context get",
            "guild workspace context edit",
            "guild workspace context publish",
            "guild agent init",
            "guild agent clone",
            "guild agent pull",
            "guild agent test",
            "guild agent test --ephemeral",
            "guild agent chat",
            "guild agent save",
            "guild agent save --publish",
            "guild agent publish",
            "guild agent publish --wait",
            "guild agent unpublish",
            "guild agent revalidate",
            "guild agent get",
            "guild agent versions",
            "guild agent code",
            "guild chat --agent",
            "guild chat --workspace",
            "guild session list",
            "guild session get",
            "guild session events",
            "guild session tasks",
            "guild session send",
        ),
        "Guild CLI syntax and troubleshooting only.",
    ),
    "sdk_specialist": SpecialistCommandPolicy("sdk_specialist", (), "Code edits only."),
    "tester": SpecialistCommandPolicy(
        "tester",
        (
            "guild agent test",
            "guild agent test --ephemeral",
            "guild agent chat",
        ),
        "Validation only.",
    ),
    "session_specialist": SpecialistCommandPolicy(
        "session_specialist",
        (
            "guild workspace current",
            "guild workspace get",
            "guild workspace agent list",
            "guild chat --agent",
            "guild chat --workspace",
            "guild session list",
            "guild session get",
            "guild session events",
            "guild session tasks",
            "guild session send",
        ),
        "Live session validation only.",
    ),
    "publisher": SpecialistCommandPolicy(
        "publisher",
        (
            "guild agent save --publish",
            "guild agent publish",
            "guild agent publish --wait",
            "guild agent unpublish",
            "guild agent versions",
            "guild workspace get",
            "guild workspace select",
            "guild workspace current",
            "guild workspace agent add",
            "guild workspace agent list",
            "guild workspace agent remove",
            "guild workspace context list",
            "guild workspace context get",
            "guild workspace context edit",
            "guild workspace context publish",
            "guild chat --workspace",
            "guild session list",
            "guild session get",
        ),
        "Publish/install only after validation.",
    ),
    "documentation_specialist": SpecialistCommandPolicy("documentation_specialist", (), "Workspace README only."),
    "context_specialist": SpecialistCommandPolicy("context_specialist", (), "Dormant unless explicitly needed."),
    "editor": SpecialistCommandPolicy("editor", (), "No Guild CLI execution."),
    "validator": SpecialistCommandPolicy("validator", (), "Read-only, no Guild CLI execution."),
    "integration_specialist": SpecialistCommandPolicy("integration_specialist", (), "No Guild CLI execution."),
    "trigger_specialist": SpecialistCommandPolicy("trigger_specialist", (), "No Guild CLI execution."),
}


def command_policy_metadata(specialist: str) -> dict[str, Any]:
    policy = SPECIALIST_COMMAND_POLICIES[specialist]
    return asdict(policy)


def evaluate_specialist_command(specialist: str, command: str) -> CommandPolicyDecision:
    policy = SPECIALIST_COMMAND_POLICIES[specialist]
    normalized = normalize_shell_command(command)
    if not normalized:
        return CommandPolicyDecision(False, specialist, command, None, "Empty command.")
    for rule in policy.allowed_commands:
        if _matches_rule(normalized, rule):
            return CommandPolicyDecision(True, specialist, command, rule, "Allowed by specialist policy.")
    return CommandPolicyDecision(
        False,
        specialist,
        command,
        None,
        f"{specialist} cannot run `{normalized}` under the Guild CLI policy.",
    )


def evaluate_execute_request(context: GuildExecutionContext) -> CommandPolicyDecision:
    normalized = normalize_shell_command(context.command)
    if not normalized:
        return CommandPolicyDecision(False, context.specialist, context.command, None, "Empty command.")

    primary = extract_primary_command(normalized)
    specialist = context.specialist or "main"
    if primary.startswith("guild "):
        if specialist == "main":
            return CommandPolicyDecision(
                False,
                specialist,
                context.command,
                None,
                "Main orchestrator must delegate Guild CLI execution to a specialist.",
            )
        policy_decision = evaluate_specialist_command(specialist, primary)
        if not policy_decision.allowed:
            return policy_decision
        guild_guard = validate_guild_command_scope(
            specialist=specialist,
            command=context.command,
            workspace_root=context.workspace_root,
            current_cwd=context.current_cwd,
        )
        if guild_guard is not None:
            return guild_guard
        return CommandPolicyDecision(True, specialist, context.command, policy_decision.matched_rule, "Allowed by specialist policy.")

    if specialist in {"main", "cli_specialist"}:
        return CommandPolicyDecision(True, specialist, context.command, None, "Allowed non-Guild shell command.")
    return evaluate_specialist_command(specialist, normalized)


def normalize_shell_command(command: str) -> str:
    stripped = command.strip()
    if not stripped:
        return ""
    return " ".join(shlex.split(stripped))


def extract_primary_command(command: str) -> str:
    segments = [segment.strip() for segment in re.split(r"\s*(?:&&|;)\s*", command) if segment.strip()]
    for segment in reversed(segments):
        if not segment.startswith("cd "):
            return segment
    return segments[-1] if segments else command


def validate_guild_command_scope(
    *,
    specialist: str,
    command: str,
    workspace_root: Path,
    current_cwd: Path | None,
) -> CommandPolicyDecision | None:
    normalized = normalize_shell_command(command)
    primary = extract_primary_command(normalized)
    agent_scope = resolve_agent_scope_path(command=normalized, workspace_root=workspace_root, current_cwd=current_cwd)
    if primary.startswith("guild agent init"):
        if agent_scope is None:
            return CommandPolicyDecision(
                False,
                specialist,
                command,
                "guild agent init",
                "Run `guild agent init` only inside `agents/<agent-name>/` or with `--directory agents/<agent-name>`.",
            )
    if primary.startswith(("guild agent test", "guild agent save", "guild agent chat", "guild agent pull")):
        if agent_scope is None:
            return CommandPolicyDecision(
                False,
                specialist,
                command,
                primary.split()[0] + " " + primary.split()[1],
                "Agent-local Guild commands must run from `agents/<agent-name>/` or a validated `--directory` target.",
            )
    return None


def resolve_agent_scope_path(*, command: str, workspace_root: Path, current_cwd: Path | None) -> Path | None:
    directory_from_flag = extract_directory_flag(command)
    if directory_from_flag is not None:
        resolved = resolve_command_path(directory_from_flag, workspace_root, current_cwd)
        return resolved if is_valid_agent_directory(resolved, workspace_root) else None
    cd_target = extract_cd_target(command)
    if cd_target is not None:
        resolved = resolve_command_path(cd_target, workspace_root, current_cwd)
        return resolved if is_valid_agent_directory(resolved, workspace_root) else None
    if current_cwd is None:
        return None
    return current_cwd if is_valid_agent_directory(current_cwd, workspace_root) else None


def extract_directory_flag(command: str) -> str | None:
    tokens = shlex.split(command)
    for index, token in enumerate(tokens):
        if token == "--directory" and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--directory="):
            return token.split("=", 1)[1]
    return None


def extract_cd_target(command: str) -> str | None:
    segments = [segment.strip() for segment in re.split(r"\s*(?:&&|;)\s*", command) if segment.strip()]
    for segment in segments:
        if segment.startswith("cd "):
            parts = shlex.split(segment)
            if len(parts) >= 2:
                return parts[1]
    return None


def resolve_command_path(path_text: str, workspace_root: Path, current_cwd: Path | None) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate.resolve()
    base = current_cwd.resolve() if current_cwd is not None else workspace_root.resolve()
    return (base / candidate).resolve()


def is_valid_agent_directory(path: Path, workspace_root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return False
    parts = relative.parts
    return len(parts) >= 2 and parts[0] == "agents"


def _matches_rule(command: str, rule: str) -> bool:
    if command == rule:
        return True
    return command.startswith(rule + " ")
