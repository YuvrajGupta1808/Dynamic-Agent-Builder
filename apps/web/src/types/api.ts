export type WorkspaceMode = "local" | "uploaded" | "remote_sandbox";
export type SessionMode = "ask_before_edits" | "accept_edits" | "accept_everything";

/** One chat turn for multi-turn agent runs (matches backend `ChatMessage`). */
export type ChatTurn = { role: "user" | "assistant" | "system"; content: string };

export interface AppConfig {
  defaultModel: string;
  models: Array<{ value: string; name: string }>;
  modes: Array<{ id: SessionMode; name: string }>;
  workspaceModes: Array<{ id: WorkspaceMode; name: string; enabled: boolean }>;
  allowedRoots: string[];
  workspaceRoot: string;
  currentWorkingDirectory: string;
  tokenRequired: boolean;
}

export interface WorkspaceSummary {
  name: string;
  path: string;
  created?: boolean;
}

export interface SessionRecord {
  id: string;
  cwd: string;
  workspaceMode: WorkspaceMode;
  mode: SessionMode;
  model: string;
  createdAt: string;
}

export interface FileTreeNode {
  name: string;
  path: string;
  type: "file" | "directory";
  size?: number | null;
  children: FileTreeNode[];
}

export interface FileContentResponse {
  path: string;
  content: string;
  truncated: boolean;
}

export interface DiffResponse {
  diff: string;
  changedFiles: string[];
}

export interface TodoItem {
  id: string;
  text: string;
  status: "pending" | "active" | "completed";
}

export interface StreamEvent {
  type:
    | "token"
    | "thinking"
    | "update"
    | "custom"
    | "todo"
    | "tool_call"
    | "subagent"
    | "file_change"
    | "approval_required"
    | "error"
    | "done";
  runId: string;
  sessionId: string;
  sequence: number;
  source: string;
  message?: string | null;
  data: Record<string, unknown>;
}

export interface ApprovalData {
  runId: string;
  interruptId: string;
  tool: string;
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "rejected";
}
