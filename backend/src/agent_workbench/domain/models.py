"""Pydantic models shared by backend routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WorkspaceMode = Literal["local", "uploaded", "remote_sandbox"]
SessionMode = Literal["ask_before_edits", "accept_edits", "accept_everything"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CreateSessionRequest(StrictModel):
    cwd: str | None = None
    workspace: str | None = None
    workspace_mode: WorkspaceMode = Field(default="local", alias="workspaceMode")
    mode: SessionMode = "accept_edits"
    model: str | None = None


class CreateWorkspaceRequest(StrictModel):
    name: str


class WorkspaceSummary(StrictModel):
    name: str
    path: str
    created: bool = False


class SessionRecord(StrictModel):
    id: str
    cwd: str
    workspace_mode: WorkspaceMode = Field(alias="workspaceMode")
    mode: SessionMode
    model: str
    created_at: str = Field(alias="createdAt")


class ChatMessage(StrictModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(default="", max_length=200_000)


class RunStreamRequest(StrictModel):
    """Either send `message` (single user turn) or `messages` (full transcript for multi-turn)."""

    message: str = ""
    model: str | None = None
    mode: SessionMode | None = None
    messages: list[ChatMessage] | None = None

    @model_validator(mode="after")
    def _require_some_input(self) -> RunStreamRequest:
        if self.messages is not None and len(self.messages) > 0:
            return self
        if (self.message or "").strip():
            return self
        raise ValueError("Provide non-empty `message` or at least one entry in `messages`")


class GenerateTitleRequest(StrictModel):
    prompt: str
    model: str | None = None


class InterruptDecision(StrictModel):
    decision: Literal["approve", "reject"]
    reason: str | None = None


class FileTreeNode(StrictModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int | None = None
    children: list["FileTreeNode"] = Field(default_factory=list)


class FileContentResponse(StrictModel):
    path: str
    content: str
    truncated: bool = False


class DiffResponse(StrictModel):
    diff: str
    changed_files: list[str] = Field(default_factory=list, alias="changedFiles")


class ApplyFileRequest(StrictModel):
    path: str
    content: str


class StreamEvent(StrictModel):
    type: Literal[
        "token",
        "thinking",
        "update",
        "custom",
        "todo",
        "tool_call",
        "subagent",
        "file_change",
        "approval_required",
        "error",
        "done",
    ]
    run_id: str = Field(alias="runId")
    session_id: str = Field(alias="sessionId")
    sequence: int
    source: str = "main"
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ApprovalRecord(StrictModel):
    run_id: str = Field(alias="runId")
    interrupt_id: str = Field(alias="interruptId")
    tool: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "approved", "rejected"] = "pending"
