import type {
  AppConfig,
  DiffResponse,
  FileContentResponse,
  FileTreeNode,
  SessionMode,
  SessionRecord,
  StreamEvent,
  WorkspaceSummary,
  WorkspaceMode,
} from "../types/api";
import { parseSseFrames } from "./sse";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8787";
const TOKEN_KEY = "agent-workbench-token";
const DEFAULT_TOKEN = import.meta.env.VITE_WORKBENCH_TOKEN ?? "dev-local-token";

export function getToken() {
  const existing = localStorage.getItem(TOKEN_KEY);
  if (existing) return existing;
  localStorage.setItem(TOKEN_KEY, DEFAULT_TOKEN);
  return DEFAULT_TOKEN;
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const doFetch = async (token: string) =>
    fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(init?.headers ?? {}),
      },
    });

  let response: Response;
  try {
    response = await doFetch(getToken());
  } catch (err) {
    throw new Error(`API unreachable at ${API_BASE}`);
  }

  if (response.status === 401) {
    setToken(DEFAULT_TOKEN);
    response = await doFetch(DEFAULT_TOKEN);
  }

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return (await response.json()) as T;
}

export function getConfig() {
  return requestJson<AppConfig>("/api/config");
}

export function getWorkspaces() {
  return requestJson<{ workspaces: WorkspaceSummary[] }>("/api/workspaces");
}

export function createWorkspace(name: string) {
  return requestJson<WorkspaceSummary>("/api/workspaces", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function createSession(payload: {
  cwd?: string;
  workspace?: string;
  workspaceMode: WorkspaceMode;
  mode: SessionMode;
  model: string;
}) {
  return requestJson<SessionRecord>("/api/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generateChatTitle(sessionId: string, payload: { prompt: string; model?: string }) {
  return requestJson<{ title: string }>(`/api/sessions/${sessionId}/title`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getFileTree(sessionId: string) {
  return requestJson<FileTreeNode>(`/api/sessions/${sessionId}/files/tree`);
}

export function getFileContent(sessionId: string, path: string) {
  return requestJson<FileContentResponse>(`/api/sessions/${sessionId}/files/content?path=${encodeURIComponent(path)}`);
}

export function getDiff(sessionId: string, path?: string) {
  const suffix = path ? `?path=${encodeURIComponent(path)}` : "";
  return requestJson<DiffResponse>(`/api/sessions/${sessionId}/files/diff${suffix}`);
}

export function applyFile(sessionId: string, path: string, content: string) {
  return requestJson<FileContentResponse>(`/api/sessions/${sessionId}/files/apply`, {
    method: "POST",
    body: JSON.stringify({ path, content }),
  });
}

export function decideInterrupt(runId: string, interruptId: string, decision: "approve" | "reject") {
  return requestJson(`/api/runs/${runId}/interrupts/${interruptId}`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

export async function streamRun(
  sessionId: string,
  payload: { message: string; model?: string; mode?: SessionMode },
  onEvent: (event: StreamEvent) => void,
) {
  const STREAM_TIMEOUT_MS = 90_000;
  let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
  const resetTimeout = (controller: AbortController) => {
    if (timeoutHandle) clearTimeout(timeoutHandle);
    timeoutHandle = setTimeout(() => controller.abort("stream-timeout"), STREAM_TIMEOUT_MS);
  };

  const controller = new AbortController();
  const doFetch = async (token: string) =>
    fetch(`${API_BASE}/api/sessions/${sessionId}/runs/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

  let response: Response;
  try {
    resetTimeout(controller);
    response = await doFetch(getToken());
  } catch {
    if (timeoutHandle) clearTimeout(timeoutHandle);
    if (controller.signal.aborted) {
      throw new Error("Run timed out waiting for backend stream");
    }
    throw new Error(`API unreachable at ${API_BASE}`);
  }
  if (response.status === 401) {
    setToken(DEFAULT_TOKEN);
    resetTimeout(controller);
    response = await doFetch(DEFAULT_TOKEN);
  }

  if (!response.ok || !response.body) {
    if (timeoutHandle) clearTimeout(timeoutHandle);
    throw new Error(await response.text());
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      resetTimeout(controller);
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseFrames(buffer);
      buffer = parsed.rest;
      parsed.events.forEach(onEvent);
    }
    if (buffer.trim()) {
      const tail = parseSseFrames(`${buffer}\n\n`);
      tail.events.forEach(onEvent);
    }
  } catch {
    if (controller.signal.aborted) {
      throw new Error("Run timed out waiting for backend stream");
    }
    throw new Error("Stream interrupted while reading backend events");
  } finally {
    if (timeoutHandle) clearTimeout(timeoutHandle);
  }
}
