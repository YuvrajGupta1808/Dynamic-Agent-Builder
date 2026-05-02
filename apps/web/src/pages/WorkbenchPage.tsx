import Editor from "@monaco-editor/react";
import * as Dialog from "@radix-ui/react-dialog";
import {
    ArrowUp,
    Check,
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    Code2,
    FilePlus2,
    FolderGit2,
    History,
    Mic,
    MoreHorizontal,
    PanelLeftClose,
    Plus,
    RefreshCw,
    Save,
    Square,
    SquareTerminal,
    X,
} from "lucide-react";
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ChangeEvent, type RefObject } from "react";
import ReactMarkdown from "react-markdown";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";
import { Link } from "react-router-dom";
import remarkGfm from "remark-gfm";

import { FileTree } from "../components/FileTree";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import {
    ApiError,
    applyFile,
    createSession,
    createWorkspace,
    decideInterrupt,
    getConfig,
    getFileContent,
    getFileTree,
    getWorkspaceHealth,
    getWorkspaces,
    openTerminalSocket,
    repairWorkspace,
    sendTerminalEvent,
    streamRun,
    transcribeAudio,
} from "../lib/api";
import { setRequireClerkJwt } from "../lib/auth-token";
import { renderTerminalAnsi } from "../lib/terminal-ansi";
import { cn } from "../lib/utils";
import type {
    AppConfig,
    ApprovalData,
    ChatContentPart,
    FileTreeNode,
    SessionMode,
    SessionRecord,
    StreamEvent,
    TerminalServerEvent,
    TodoItem,
    WorkspaceHealth,
    WorkspaceSummary,
} from "../types/api";

export type RunBlockKind = "thinking" | "assistant" | "tool" | "subagent" | "approval" | "error";

export type RunBlock = {
  id: string;
  kind: RunBlockKind;
  text: string;
  eventType?: StreamEvent["type"] | "fallback_assistant";
};

type CompletedRun = {
  id: string;
  prompt: string;
  promptImages: string[];
  blocks: RunBlock[];
  finalOutput: string;
};

type ImageAttachment = {
  id: string;
  name: string;
  dataUrl: string;
};

type ChatThread = {
  id: string;
  title: string;
  runs: CompletedRun[];
  /** Backend session id + metadata; one per UI chat, lazy-created on first send. */
  backendSession?: SessionRecord | null;
};

type TerminalTab = "user" | "agent";

const WorkbenchEditorPane = memo(function WorkbenchEditorPane({
  selectedPath,
  workspaceBlocked,
  workspaceMissing,
  workspaceIssue,
  hasUnsavedChanges,
  isSaving,
  saveLabel,
  editorLanguage,
  fileContent,
  onFileContentChange,
  onCloseFile,
  onSaveFile,
  onRepairWorkspace,
  onOpenWorkspaceModal,
  activeTerminalTab,
  agentTerminalLines,
  agentTerminalOutputRef,
  userTerminalOutputRef,
  renderedUserTerminalHtml,
  userTerminalPromptLabel,
  userTerminalCommand,
  userTerminalConnected,
  terminalPanelRef,
  onActiveTerminalTabChange,
  onClearAgentTerminal,
  onClearUserTerminal,
  onUserTerminalCommandChange,
  onRunUserTerminalCommand,
  onInterruptUserTerminal,
  onToggleTerminal,
}: {
  selectedPath: string;
  workspaceBlocked: boolean;
  workspaceMissing: boolean;
  workspaceIssue: WorkspaceHealth | null;
  hasUnsavedChanges: boolean;
  isSaving: boolean;
  saveLabel: string;
  editorLanguage: string;
  fileContent: string;
  onFileContentChange: (value: string) => void;
  onCloseFile: () => void;
  onSaveFile: () => void;
  onRepairWorkspace: () => void;
  onOpenWorkspaceModal: () => void;
  activeTerminalTab: TerminalTab;
  agentTerminalLines: string[];
  agentTerminalOutputRef: RefObject<HTMLPreElement | null>;
  userTerminalOutputRef: RefObject<HTMLDivElement | null>;
  renderedUserTerminalHtml: string;
  userTerminalPromptLabel: string;
  userTerminalCommand: string;
  userTerminalConnected: boolean;
  terminalPanelRef: ReturnType<typeof usePanelRef>;
  onActiveTerminalTabChange: (tab: TerminalTab) => void;
  onClearAgentTerminal: () => void;
  onClearUserTerminal: () => void;
  onUserTerminalCommandChange: (value: string) => void;
  onRunUserTerminalCommand: () => void;
  onInterruptUserTerminal: () => void;
  onToggleTerminal: () => void;
}) {
  return (
    <section className="workbench-pane workbench-pane-fill">
      <header className="editor-tabbar">
        <div className="editor-tabs-row">
          {selectedPath ? (
            <div className="tab active editor-tab-with-close" role="presentation">
              <FilePlus2 />
              <span className="editor-tab-label">{selectedPath}</span>
              <button type="button" className="editor-tab-close" aria-label="Close file" onClick={onCloseFile}>
                <X />
              </button>
            </div>
          ) : (
            <span className="editor-tab-placeholder">
              {workspaceBlocked ? "Workspace blocked" : workspaceMissing ? "Workspace" : "No file open"}
            </span>
          )}
        </div>
        <div className="editor-actions">
          <Button
            disabled={!selectedPath || !hasUnsavedChanges || isSaving || workspaceMissing || workspaceBlocked}
            variant="ghost"
            size="sm"
            onClick={onSaveFile}
            title={saveLabel}
          >
            <Save data-icon="inline-start" />
            {saveLabel}
          </Button>
          {selectedPath ? (
            <button type="button" className="editor-tab-close" aria-label="Close file" onClick={onCloseFile}>
              <X />
            </button>
          ) : null}
        </div>
      </header>

      <Group orientation="vertical" className="workbench-center-group" resizeTargetMinimumSize={{ coarse: 18, fine: 10 }}>
        <Panel id="editorPanel" defaultSize="72%" minSize="38%" className="workbench-center-editor-panel">
          <section className={`editor-area ${workspaceMissing || workspaceBlocked ? "editor-area-idle" : ""}`}>
            {workspaceBlocked ? (
              <WorkspaceIssueCard issue={workspaceIssue} busy={false} onRepair={onRepairWorkspace} />
            ) : workspaceMissing ? (
              <div className="workbench-empty-canvas">
                <p className="workbench-empty-kicker">Getting started</p>
                <h2 className="workbench-empty-heading">Create a workspace</h2>
                <p className="workbench-empty-lead">
                  You’ll get an isolated folder with a README, a file tree, and a safe place for the agent to work, nothing outside it
                  unless you configure that.
                </p>
                <Button type="button" size="default" className="workbench-empty-cta" onClick={onOpenWorkspaceModal}>
                  Get started
                </Button>
              </div>
            ) : (
              <Editor
                height="100%"
                language={editorLanguage}
                theme="vs-dark"
                value={fileContent}
                onChange={(value) => onFileContentChange(value ?? "")}
                options={{
                  automaticLayout: true,
                  fontFamily: "JetBrains Mono, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                  fontSize: 13,
                  lineHeight: 21,
                  minimap: { enabled: false },
                  renderLineHighlight: "line",
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                }}
              />
            )}
          </section>
        </Panel>

        <Separator className="resize-handle resize-handle-vertical" />

        <Panel
          id="terminalPanel"
          panelRef={terminalPanelRef}
          collapsible
          collapsedSize={0}
          defaultSize="28%"
          minSize="14%"
          maxSize="55%"
          className="workbench-center-terminal-panel"
        >
          <section className={`terminal-dock ${workspaceMissing || workspaceBlocked ? "terminal-dock-idle" : ""}`}>
            <div className="terminal-header">
              <div>
                <SquareTerminal />
                <button
                  type="button"
                  className={activeTerminalTab === "user" ? "terminal-tab active" : "terminal-tab"}
                  onClick={() => onActiveTerminalTabChange("user")}
                >
                  User Terminal
                </button>
                <button
                  type="button"
                  className={activeTerminalTab === "agent" ? "terminal-tab active" : "terminal-tab"}
                  onClick={() => onActiveTerminalTabChange("agent")}
                >
                  Agent Terminal
                </button>
              </div>
              <div className="terminal-actions">
                {activeTerminalTab === "user" ? (
                  <Button variant="ghost" size="sm" onClick={onInterruptUserTerminal}>
                    Stop
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={activeTerminalTab === "user" ? onClearUserTerminal : onClearAgentTerminal}
                >
                  Clear
                </Button>
                <Button variant="ghost" size="icon" type="button" title="Close terminal" onClick={onToggleTerminal}>
                  <X />
                </Button>
              </div>
            </div>
            {activeTerminalTab === "user" ? (
              <>
                <div className="terminal-output-shell">
                  <div
                    className="terminal-output terminal-output-html"
                    ref={userTerminalOutputRef}
                    tabIndex={-1}
                    dangerouslySetInnerHTML={{ __html: renderedUserTerminalHtml }}
                  />
                  <form
                    className="terminal-inline-prompt"
                    onSubmit={(event) => {
                      event.preventDefault();
                      onRunUserTerminalCommand();
                    }}
                  >
                    <span className="terminal-prompt-label">{userTerminalPromptLabel}</span>
                    <span className="terminal-prompt-arrow">❯</span>
                    <Input
                      value={userTerminalCommand}
                      onChange={(event) => onUserTerminalCommandChange(event.target.value)}
                      placeholder={userTerminalConnected ? "" : "Open a workspace to start the terminal"}
                      readOnly={!userTerminalConnected}
                      className="terminal-inline-input"
                    />
                  </form>
                </div>
              </>
            ) : (
              <pre className="terminal-output" ref={agentTerminalOutputRef} tabIndex={-1}>
                {agentTerminalLines.join("\n")}
              </pre>
            )}
          </section>
        </Panel>
      </Group>
    </section>
  );
});

const AgentRunTimeline = memo(function AgentRunTimeline({
  runs,
  lastSubmittedPrompt,
  liveRunBlocks,
  isRunning,
  approval,
  pendingApprovalsCount,
  approvalFeedback,
  approvalEditDraft,
  approvalEditMode,
  isDecidingApproval,
  onFeedbackChange,
  onEditDraftChange,
  onToggleEditMode,
  onReject,
  onApprove,
  onSubmitEdit,
}: {
  runs: CompletedRun[];
  lastSubmittedPrompt: string;
  liveRunBlocks: RunBlock[];
  isRunning: boolean;
  approval: ApprovalData | null;
  pendingApprovalsCount: number;
  approvalFeedback: string;
  approvalEditDraft: string;
  approvalEditMode: boolean;
  isDecidingApproval: boolean;
  onFeedbackChange: (value: string) => void;
  onEditDraftChange: (value: string) => void;
  onToggleEditMode: (value: boolean) => void;
  onReject: () => void;
  onApprove: () => void;
  onSubmitEdit: () => void;
}) {
  if (!runs.length && !lastSubmittedPrompt && liveRunBlocks.length === 0) {
    return (
      <div className="agent-empty-state">
        <h3>How can I help you today?</h3>
        <p>Ask anything or describe the edit you want to make.</p>
      </div>
    );
  }

  return (
    <>
      {runs.map((run) => (
        <div key={run.id} className="timeline-run-group">
          <article className="timeline-card user">
            {renderMarkdownText(run.prompt)}
            {run.promptImages.length > 0 && (
              <div className="timeline-inline-images">
                {run.promptImages.map((url) => (
                  <img key={url} src={url} alt="User upload" className="timeline-inline-image" />
                ))}
              </div>
            )}
          </article>
          {run.blocks.map((block) => renderRunBlock(block))}
        </div>
      ))}

      {lastSubmittedPrompt ? (
        <div className="timeline-run-group current-live-run">
          <article className="timeline-card user">{renderMarkdownText(lastSubmittedPrompt)}</article>
          {liveRunBlocks.map((block) => renderRunBlock(block))}
          {isRunning && liveRunBlocks.length === 0 ? (
            <article className="timeline-card thinking">
              <p>Thinking...</p>
            </article>
          ) : null}
          {approval ? (
            <ApprovalReviewCard
              approval={approval}
              pendingCount={pendingApprovalsCount}
              feedback={approvalFeedback}
              editDraft={approvalEditDraft}
              editMode={approvalEditMode}
              busy={isDecidingApproval}
              onFeedbackChange={onFeedbackChange}
              onEditDraftChange={onEditDraftChange}
              onToggleEditMode={onToggleEditMode}
              onReject={onReject}
              onApprove={onApprove}
              onSubmitEdit={onSubmitEdit}
            />
          ) : null}
        </div>
      ) : null}
    </>
  );
});

const TERMINAL_LINE_LIMIT = 400;
const LIVE_FILE_REFRESH_DEBOUNCE_MS = 250;
const LIVE_FILE_REFRESH_POLL_MS = 2000;

export function WorkbenchPage() {
  const FIREWORKS_MODEL_OPTIONS = [
    "openai:accounts/fireworks/models/glm-4p7",
    "openai:accounts/fireworks/models/qwen3p6-plus",
  ] as const;

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWorkspace, setActiveWorkspace] = useState<string>("");
  const [workspaceModalOpen, setWorkspaceModalOpen] = useState(false);
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [session, setSession] = useState<SessionRecord | null>(null);
  const [workspaceIssue, setWorkspaceIssue] = useState<WorkspaceHealth | null>(null);
  const [tree, setTree] = useState<FileTreeNode | null>(null);
  const [selectedPath, setSelectedPath] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [activeTerminalTab, setActiveTerminalTab] = useState<TerminalTab>("user");
  const [agentTerminalLines, setAgentTerminalLines] = useState<string[]>(["Agent terminal ready."]);
  const [userTerminalBuffer, setUserTerminalBuffer] = useState("Open a workspace to start the user terminal.\n");
  const [userTerminalCommand, setUserTerminalCommand] = useState("");
  const [userTerminalConnected, setUserTerminalConnected] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalData[]>([]);
  const [approvalFeedback, setApprovalFeedback] = useState("");
  const [approvalEditDraft, setApprovalEditDraft] = useState("");
  const [approvalEditMode, setApprovalEditMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liveRunBlocks, setLiveRunBlocks] = useState<RunBlock[]>([]);
  const [lastSubmittedPrompt, setLastSubmittedPrompt] = useState("");
  const [agentTitle, setAgentTitle] = useState("Agents");
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedMode, setSelectedMode] = useState<SessionMode>("accept_edits");
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [showModeMenu, setShowModeMenu] = useState(false);
  const [recentPrompts, setRecentPrompts] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showActions, setShowActions] = useState(false);
  const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribingAudio, setIsTranscribingAudio] = useState(false);
  const [isDecidingApproval, setIsDecidingApproval] = useState(false);
  const [chatThreads, setChatThreads] = useState<ChatThread[]>([{ id: crypto.randomUUID(), title: "Agents", runs: [] }]);
  const [activeThreadId, setActiveThreadId] = useState<string>("");
  const activeThread = chatThreads.find((thread) => thread.id === activeThreadId) ?? chatThreads[0];
  const approval = pendingApprovals[0] ?? null;
  const structuredEventsSeenRef = useRef(false);
  const backendFailureRef = useRef(false);
  const runInFlightRef = useRef(false);
  const didBootRef = useRef(false);
  const chatPaneRef = useRef<HTMLDivElement>(null);
  const agentTerminalOutputRef = useRef<HTMLPreElement>(null);
  const userTerminalOutputRef = useRef<HTMLDivElement>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaChunksRef = useRef<BlobPart[]>([]);
  const liveRefreshDebounceRef = useRef<number | null>(null);
  const liveRefreshPollRef = useRef<number | null>(null);
  const streamFlushRafRef = useRef<number | null>(null);
  const terminalSocketRef = useRef<WebSocket | null>(null);
  const explorerPanelRef = usePanelRef();
  const chatPanelRef = usePanelRef();
  const terminalPanelRef = usePanelRef();

  const COMPOSER_TEXTAREA_MAX_PX = 320;

  const resizeComposerTextarea = useCallback(() => {
    const ta = composerTextareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, COMPOSER_TEXTAREA_MAX_PX)}px`;
  }, []);

  const appendAgentTerminalLines = useCallback((lines: string[]) => {
    if (!lines.length) return;
    setAgentTerminalLines((current) => [...current, ...lines].slice(-TERMINAL_LINE_LIMIT));
  }, []);

  const appendUserTerminalText = useCallback((text: string) => {
    if (!text) return;
    setUserTerminalBuffer((current) => {
      const next = `${current}${text}`;
      if (next.length <= 80_000) return next;
      return next.slice(next.length - 80_000);
    });
  }, []);

  const clearLiveWorkspaceRefresh = useCallback(() => {
    if (liveRefreshDebounceRef.current !== null) {
      window.clearTimeout(liveRefreshDebounceRef.current);
      liveRefreshDebounceRef.current = null;
    }
    if (liveRefreshPollRef.current !== null) {
      window.clearInterval(liveRefreshPollRef.current);
      liveRefreshPollRef.current = null;
    }
  }, []);

  const scrollChatToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      const el = chatPaneRef.current;
      if (!el) return;
      el.scrollTop = el.scrollHeight;
    });
  }, []);

  const scrollTerminalToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      const el = activeTerminalTab === "user" ? userTerminalOutputRef.current : agentTerminalOutputRef.current;
      if (!el) return;
      el.scrollTop = el.scrollHeight;
    });
  }, [activeTerminalTab]);

  useEffect(() => {
    if (didBootRef.current) return;
    didBootRef.current = true;
    void boot();
  }, []);

  useEffect(() => () => {
    clearLiveWorkspaceRefresh();
    if (streamFlushRafRef.current !== null) {
      cancelAnimationFrame(streamFlushRafRef.current);
      streamFlushRafRef.current = null;
    }
    terminalSocketRef.current?.close();
    terminalSocketRef.current = null;
  }, [clearLiveWorkspaceRefresh]);

  useEffect(() => {
    if (!activeThreadId && chatThreads.length) {
      setActiveThreadId(chatThreads[0].id);
    }
  }, [activeThreadId, chatThreads]);

  useEffect(() => {
    if (!approval) {
      setApprovalFeedback("");
      setApprovalEditDraft("");
      setApprovalEditMode(false);
      return;
    }
    setApprovalFeedback("");
    setApprovalEditDraft(defaultEditedActionDraft(approval));
    setApprovalEditMode(false);
  }, [approval?.interruptId]);

  useLayoutEffect(() => {
    resizeComposerTextarea();
  }, [prompt, resizeComposerTextarea]);

  useLayoutEffect(() => {
    scrollChatToBottom();
  }, [
    scrollChatToBottom,
    liveRunBlocks,
    lastSubmittedPrompt,
    isRunning,
    activeThreadId,
    activeThread?.runs.length,
  ]);

  useLayoutEffect(() => {
    scrollTerminalToBottom();
  }, [scrollTerminalToBottom, agentTerminalLines, userTerminalBuffer]);

  useEffect(() => {
    clearLiveWorkspaceRefresh();
    if (!isRunning || !session?.id || workspaceIssue) return;
    liveRefreshPollRef.current = window.setInterval(() => {
      void refreshWorkspace(session.id).catch((err) => {
        setError(err instanceof Error ? err.message : "Unable to refresh workspace");
      });
    }, LIVE_FILE_REFRESH_POLL_MS);
    return clearLiveWorkspaceRefresh;
  }, [clearLiveWorkspaceRefresh, isRunning, session?.id, workspaceIssue]);

  useEffect(() => {
    const pre = agentTerminalOutputRef.current;
    if (!pre) return;
    pre.textContent = agentTerminalLines.join("\n");
  }, [agentTerminalLines]);

  useEffect(() => {
    terminalSocketRef.current?.close();
    terminalSocketRef.current = null;
    if (!session?.id || workspaceIssue) {
      setUserTerminalConnected(false);
      setUserTerminalBuffer(
        workspaceIssue ? `${workspaceIssue.message}\n` : "Open a workspace to start the user terminal.\n",
      );
      return;
    }
    let active = true;
    setUserTerminalConnected(false);
    setUserTerminalBuffer("");
    void openTerminalSocket(session.id, {
      onOpen: () => {
        if (!active) return;
        setUserTerminalConnected(true);
      },
      onClose: () => {
        if (!active) return;
        setUserTerminalConnected(false);
      },
      onError: () => {
        if (!active) return;
        setUserTerminalConnected(false);
      },
      onEvent: (event: TerminalServerEvent) => {
        if (!active) return;
        if (event.type === "output") {
          appendUserTerminalText(event.data);
          return;
        }
        if (event.type === "status") {
          setUserTerminalConnected(event.status === "connected");
          return;
        }
        if (event.type === "exit") {
          setUserTerminalConnected(false);
          appendUserTerminalText(`\n[process exited ${event.exitCode}]\n`);
          return;
        }
        if (event.type === "error") {
          appendUserTerminalText(`\n[error] ${event.message}\n`);
        }
      },
    })
      .then((socket) => {
        if (!active) {
          socket.close();
          return;
        }
        terminalSocketRef.current = socket;
        sendTerminalEvent(socket, { type: "resize", cols: 120, rows: 30 });
      })
      .catch((err) => {
        if (!active) return;
        setUserTerminalConnected(false);
        setUserTerminalBuffer(`Unable to connect to terminal: ${err instanceof Error ? err.message : "Unknown error"}\n`);
      });
    return () => {
      active = false;
      terminalSocketRef.current?.close();
      terminalSocketRef.current = null;
    };
  }, [appendUserTerminalText, session?.id, session?.cwd, workspaceIssue]);

  const editorLanguage = useMemo(() => {
    if (selectedPath.endsWith(".py")) return "python";
    if (selectedPath.endsWith(".ts") || selectedPath.endsWith(".tsx")) return "typescript";
    if (selectedPath.endsWith(".json")) return "json";
    if (selectedPath.endsWith(".css")) return "css";
    if (selectedPath.endsWith(".html")) return "html";
    return "markdown";
  }, [selectedPath]);

  const renderedUserTerminalHtml = useMemo(() => renderTerminalAnsi(userTerminalBuffer), [userTerminalBuffer]);
  const userTerminalPromptLabel = useMemo(() => {
    const cwd = session?.cwd ?? "";
    const segments = cwd.split("/").filter(Boolean);
    return segments.at(-1) ?? "workspace";
  }, [session?.cwd]);

  async function boot() {
    try {
      const nextConfig = await getConfig();
      // Match frontend bearer strategy with backend capability.
      setRequireClerkJwt(Boolean(nextConfig.clerkAuthEnabled));
      setConfig(nextConfig);
      setSelectedModel(nextConfig.defaultModel);
      setSelectedMode("accept_edits");
      const workspaceResponse = await getWorkspaces();
      const nextWorkspaces = workspaceResponse.workspaces;
      setWorkspaces(nextWorkspaces);
      if (nextWorkspaces.length > 0) {
        await openWorkspace(nextWorkspaces[0].name, nextConfig);
      } else {
        const tid = crypto.randomUUID();
        setActiveWorkspace("");
        setSession(null);
        setWorkspaceIssue(null);
        setTree(null);
        setSelectedPath("");
        setFileContent("");
        setSavedContent("");
        setChatThreads([{ id: tid, title: "Agents", runs: [] }]);
        setActiveThreadId(tid);
        setAgentTerminalLines([
          "Welcome to Dynamic Agent Studio.",
          "Create a workspace (center panel) to open the editor, file tree, and agent.",
        ]);
        setError(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to initialize workspace");
    }
  }

  async function refreshWorkspaces() {
    const response = await getWorkspaces();
    setWorkspaces(response.workspaces);
  }

  const openWorkspaceReadme = useCallback(async (sessionId: string) => {
    try {
      const readme = await getFileContent(sessionId, "README.md");
      setSelectedPath("README.md");
      setFileContent(readme.content);
      setSavedContent(readme.content);
    } catch {
      // Some pre-existing workspaces may not have a README; keep editor empty in that case.
    }
  }, []);

  function generateRandomWorkspaceName() {
    const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
    const randomLength = 10 + Math.floor(Math.random() * 3); // 10-12 chars
    const bytes = new Uint8Array(randomLength);
    crypto.getRandomValues(bytes);
    let name = "";
    for (let i = 0; i < bytes.length; i += 1) {
      name += alphabet[bytes[i] % alphabet.length];
    }
    return name;
  }

  const openWorkspaceModal = useCallback(() => {
    setNewWorkspaceName(generateRandomWorkspaceName());
    setWorkspaceModalOpen(true);
  }, []);

  function regenerateWorkspaceName() {
    setNewWorkspaceName(generateRandomWorkspaceName());
  }

  async function confirmCreateWorkspace() {
    const name = newWorkspaceName.trim();
    if (!name) return;
    try {
      const created = await createWorkspace(name);
      await refreshWorkspaces();
      setWorkspaceModalOpen(false);
      await openWorkspace(created.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create workspace");
    }
  }

  const refreshWorkspace = useCallback(async (sessionId = session?.id) => {
    if (!sessionId) return;
    try {
      const nextTree = await getFileTree(sessionId);
      setTree(nextTree);
      setWorkspaceIssue(null);
    } catch (err) {
      const issue = workspaceIssueFromError(err);
      if (issue) {
        setWorkspaceIssue(issue);
        setTree(null);
        setError(issue.message);
        return;
      }
      throw err;
    }
  }, [session?.id]);

  const openWorkspace = useCallback(async (name: string, activeConfig = config) => {
    if (!activeConfig) return;
    setActiveWorkspace(name);
    setWorkspaceIssue(null);
    setSelectedPath("");
    setFileContent("");
    setSavedContent("");
    setLiveRunBlocks([]);
    setLastSubmittedPrompt("");
    setPendingApprovals([]);
    clearLiveWorkspaceRefresh();
    structuredEventsSeenRef.current = false;
    backendFailureRef.current = false;
    setTree(null);
    appendAgentTerminalLines([`$ workspace ${name}`]);
    try {
      const health = await getWorkspaceHealth(name);
      if (health.status === "invalid") {
        setWorkspaceIssue(health);
        setSession(null);
        setError(health.message);
        return;
      }

      const firstThreadId = crypto.randomUUID();
      const modelForSession = selectedModel || activeConfig.defaultModel;
      const created = await createSession({
        workspace: name,
        workspaceMode: "local",
        mode: selectedMode,
        model: modelForSession,
      });
      setChatThreads([{ id: firstThreadId, title: "Agents", runs: [], backendSession: created }]);
      setActiveThreadId(firstThreadId);
      setSession(created);
      await refreshWorkspace(created.id);
      await openWorkspaceReadme(created.id);
      setError(null);
    } catch (err) {
      const issue = workspaceIssueFromError(err);
      if (issue) {
        setWorkspaceIssue(issue);
        setSession(null);
        setTree(null);
        setError(issue.message);
        return;
      }
      throw err;
    }
  }, [appendAgentTerminalLines, clearLiveWorkspaceRefresh, config, openWorkspaceReadme, refreshWorkspace, selectedMode, selectedModel]);

  function scheduleWorkspaceRefresh(sessionId = session?.id) {
    if (!isRunning || !sessionId || workspaceIssue) return;
    if (liveRefreshDebounceRef.current !== null) {
      window.clearTimeout(liveRefreshDebounceRef.current);
    }
    liveRefreshDebounceRef.current = window.setTimeout(() => {
      liveRefreshDebounceRef.current = null;
      void refreshWorkspace(sessionId).catch((err) => {
        setError(err instanceof Error ? err.message : "Unable to refresh workspace");
      });
    }, LIVE_FILE_REFRESH_DEBOUNCE_MS);
  }

  const repairActiveWorkspace = useCallback(async () => {
    if (!activeWorkspace) return;
    try {
      const repaired = await repairWorkspace(activeWorkspace);
      setWorkspaceIssue(repaired.status === "invalid" ? repaired : null);
      appendAgentTerminalLines([
        repaired.repairedEntries.length
          ? `[repair] moved ${repaired.repairedEntries.join(", ")}`
          : "[repair] workspace already healthy",
      ]);
      if (repaired.status === "valid") {
        await openWorkspace(activeWorkspace);
      } else {
        setError(repaired.message);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to repair workspace";
      setError(message);
      appendAgentTerminalLines([`[error] ${message}`]);
    }
  }, [activeWorkspace, appendAgentTerminalLines, openWorkspace]);

  const selectFile = useCallback(async (path: string) => {
    if (!session) return;
    setSelectedPath(path);
    const content = await getFileContent(session.id, path);
    setFileContent(content.content);
    setSavedContent(content.content);
    setError(null);
  }, [session]);

  const saveFile = useCallback(async () => {
    if (!session || !selectedPath) return;
    setIsSaving(true);
    try {
      const updated = await applyFile(session.id, selectedPath, fileContent);
      setFileContent(updated.content);
      setSavedContent(updated.content);
      await refreshWorkspace();
      setWorkspaceIssue(null);
      setError(null);
      appendAgentTerminalLines([`[saved] ${selectedPath}`]);
    } catch (err) {
      const issue = workspaceIssueFromError(err);
      if (issue) {
        setWorkspaceIssue(issue);
      }
      const message = err instanceof Error ? err.message : "Unable to save file";
      setError(message);
      appendAgentTerminalLines([`[error] ${message}`]);
    } finally {
      setIsSaving(false);
    }
  }, [appendAgentTerminalLines, fileContent, selectedPath, session, refreshWorkspace]);

  async function runAgent() {
    if (!config || isRunning || runInFlightRef.current) return;
    if (!session || !activeWorkspace) {
      setError("Create or open a workspace before running the agent.");
      return;
    }
    const userPrompt = prompt.trim();
    if (!userPrompt && imageAttachments.length === 0) return;
    runInFlightRef.current = true;
    let threadIdAtSend = activeThreadId || chatThreads[0]?.id || "";
    if (!threadIdAtSend) {
      threadIdAtSend = crypto.randomUUID();
      setChatThreads([{ id: threadIdAtSend, title: "Chat", runs: [] }]);
      setActiveThreadId(threadIdAtSend);
    }
    setPrompt("");
    const activeImageAttachments = imageAttachments;
    setImageAttachments([]);
    setIsRunning(true);
    setLastSubmittedPrompt(userPrompt || (imageAttachments.length ? "Sent image attachment(s)" : ""));
    const provisionalTitle = deriveAgentTitle(userPrompt);
    setAgentTitle(provisionalTitle);
    if (userPrompt) {
      setRecentPrompts((current) => [userPrompt, ...current.filter((p) => p !== userPrompt)].slice(0, 8));
    }
    setError(null);
    setLiveRunBlocks([]);
    setPendingApprovals([]);
    structuredEventsSeenRef.current = false;
    backendFailureRef.current = false;
    appendAgentTerminalLines(["", `$ agent ${userPrompt.slice(0, 90)}`]);
    let latestReasoningText = "";
    let sawAssistantToken = false;
    let sawAnyEvent = false;
    let runFinalOutput = "";
    let latestErrorText = "";
    let nextBlocks: RunBlock[] = [];
    let liveEvents: StreamEvent[] = [];
    const activeModel = selectedModel || config.defaultModel;
    const executeRun = async (sessionId: string, priorRuns: CompletedRun[]) => {
      let queuedTerminalLines: string[] = [];
      let queuedApprovals: ApprovalData[] = [];
      let flushScheduled = false;

      const flushLiveUpdates = () => {
        flushScheduled = false;
        streamFlushRafRef.current = null;
        setLiveRunBlocks([...nextBlocks]);
        if (queuedTerminalLines.length > 0) {
          appendAgentTerminalLines(queuedTerminalLines);
          queuedTerminalLines = [];
        }
        if (queuedApprovals.length > 0) {
          const incoming = queuedApprovals;
          queuedApprovals = [];
          setPendingApprovals((current) => {
            const seen = new Set(current.map((item) => item.interruptId));
            const merged = [...current];
            for (const approvalItem of incoming) {
              if (seen.has(approvalItem.interruptId)) continue;
              seen.add(approvalItem.interruptId);
              merged.push(approvalItem);
            }
            return merged;
          });
        }
      };

      const scheduleLiveFlush = () => {
        if (flushScheduled) return;
        flushScheduled = true;
        streamFlushRafRef.current = requestAnimationFrame(() => {
          flushLiveUpdates();
        });
      };

      setChatThreads((current) => {
        return current.map((thread) => {
          if (thread.id === threadIdAtSend && thread.runs.length === 0) {
            return { ...thread, title: provisionalTitle };
          }
          return thread;
        });
      });

      const transcriptMessages = priorRuns.flatMap((r) => [
        {
          role: "user" as const,
          content:
            r.promptImages.length > 0
              ? ([{ type: "text", text: r.prompt }, ...r.promptImages.map((url) => ({ type: "image_url", image_url: { url } }))] as ChatContentPart[])
              : r.prompt,
        },
        { role: "assistant" as const, content: r.finalOutput },
      ]);
      const currentUserContent: string | ChatContentPart[] =
        activeImageAttachments.length > 0
          ? [
              { type: "text", text: userPrompt },
              ...activeImageAttachments.map(
                (item): ChatContentPart => ({ type: "image_url", image_url: { url: item.dataUrl } }),
              ),
            ]
          : userPrompt;

      const handleStreamEvent = (event: StreamEvent) => {
        liveEvents = [...liveEvents, event];
        sawAnyEvent = true;

        const terminalLine = terminalLineForEvent(event);
        if (terminalLine) {
          queuedTerminalLines.push(terminalLine);
        }
        if (event.type !== "token") {
          structuredEventsSeenRef.current = true;
        }

        const eventBlock = mapEventToRunBlock(event);
        if (eventBlock) {
          if (eventBlock.kind === "thinking") {
            latestReasoningText = eventBlock.text;
          }
          nextBlocks = appendRunBlock(nextBlocks, eventBlock);
        }

        if (event.type === "error") {
          backendFailureRef.current = true;
          latestErrorText = (event.message || "Agent run failed").trim();
        }
        if (event.type === "token" && event.message) {
          sawAssistantToken = true;
          nextBlocks = appendAssistantToken(nextBlocks, event.message);
        }
        if (event.type === "approval_required") {
          queuedApprovals.push(event.data as unknown as ApprovalData);
        }
        if (event.type === "file_change") {
          scheduleWorkspaceRefresh(sessionId);
        }
        if (event.type === "done") {
          const assistantTranscript = getAssistantTranscript(nextBlocks);
          if (assistantTranscript) {
            runFinalOutput = assistantTranscript;
          } else if (!sawAssistantToken && latestReasoningText.trim()) {
            runFinalOutput = latestReasoningText.trim();
          } else if (!runFinalOutput) {
            runFinalOutput = "Run completed without assistant text.";
          }
        }

        scheduleLiveFlush();
      };

      await streamRun(sessionId, {
        message: userPrompt,
        messages: [...transcriptMessages, { role: "user", content: currentUserContent }],
        model: activeModel,
        mode: selectedMode,
      }, handleStreamEvent);

      flushLiveUpdates();
      await refreshWorkspace(sessionId);
    };

    try {
      const threadSnapshot = chatThreads.find((t) => t.id === threadIdAtSend);
      let sessionForRun = threadSnapshot?.backendSession ?? null;

      if (!sessionForRun) {
        sessionForRun = await createSession({
          workspace: activeWorkspace,
          workspaceMode: "local",
          mode: selectedMode,
          model: activeModel,
        });
        setChatThreads((prev) =>
          prev.map((t) => (t.id === threadIdAtSend ? { ...t, backendSession: sessionForRun } : t)),
        );
      }

      setSession(sessionForRun);
      await executeRun(sessionForRun.id, threadSnapshot?.runs ?? []);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Agent run failed";
      setError(message);
      appendAgentTerminalLines([`[error] ${message}`]);
      nextBlocks = appendRunBlock(nextBlocks, { id: crypto.randomUUID(), kind: "error", text: message, eventType: "error" });
      setLiveRunBlocks(nextBlocks);
      structuredEventsSeenRef.current = true;
      backendFailureRef.current = true;
      latestErrorText = message;
      runFinalOutput = "";
    } finally {
      runInFlightRef.current = false;
      clearLiveWorkspaceRefresh();
      if (streamFlushRafRef.current !== null) {
        cancelAnimationFrame(streamFlushRafRef.current);
        streamFlushRafRef.current = null;
      }
      if (!structuredEventsSeenRef.current && !backendFailureRef.current) {
        const fallbackAssistantText = getLatestAssistantText(nextBlocks).trim();
        if (fallbackAssistantText) {
          nextBlocks = extractRunBlocksFromAssistantText(fallbackAssistantText);
          setLiveRunBlocks(nextBlocks);
        }
      }
      if (!runFinalOutput) {
        runFinalOutput = getAssistantTranscript(nextBlocks);
      }
      if (!runFinalOutput && !nextBlocks.length) {
        const fallback = sawAnyEvent
          ? "Run completed, but no assistant response text was returned."
          : "No stream events received from backend.";
        runFinalOutput = fallback;
      }
      const safeFinalOutput = (runFinalOutput || latestReasoningText || "").trim();
      const dedupedFinalOutput = latestErrorText && safeFinalOutput === latestErrorText ? "" : safeFinalOutput;
      if (userPrompt) {
        const completed: CompletedRun = {
          id: crypto.randomUUID(),
          prompt: userPrompt,
          promptImages: activeImageAttachments.map((item) => item.dataUrl),
          blocks: nextBlocks,
          finalOutput: dedupedFinalOutput || (latestErrorText ? "" : "No assistant response was returned for this run."),
        };
        setChatThreads((current) => {
          let found = false;
          const next = current.map((thread) => {
            if (thread.id !== threadIdAtSend) return thread;
            found = true;
            return { ...thread, runs: [...thread.runs, completed] };
          });
          if (found) return next;
          return [{ id: threadIdAtSend, title: provisionalTitle || "Chat", runs: [completed] }, ...next];
        });
      }
      setLastSubmittedPrompt("");
      setLiveRunBlocks([]);
      setIsRunning(false);
    }
  }

  const handleApproval = useCallback(async (
    decision: "approve" | "reject" | "edit",
    options: { reason?: string; editedAction?: Record<string, unknown> } = {},
  ) => {
    if (!approval) return;
    setIsDecidingApproval(true);
    try {
      await decideInterrupt(approval.runId, approval.interruptId, {
        decision,
        reason: options.reason,
        editedAction: options.editedAction,
      });
      const approvalLabel = approvalCheckpointLabel(approval);
      appendAgentTerminalLines([`[${decision}] ${approval.tool}${approvalLabel ? ` (${approvalLabel})` : ""}`]);
      setPendingApprovals((current) => current.filter((item) => item.interruptId !== approval.interruptId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit approval decision.");
    } finally {
      setIsDecidingApproval(false);
    }
  }, [approval, appendAgentTerminalLines]);

  const approveCurrentApproval = useCallback(async () => {
    await handleApproval("approve");
  }, [handleApproval]);

  const rejectCurrentApproval = useCallback(async () => {
    const reason = approvalFeedback.trim() || defaultRejectReason(approval);
    await handleApproval("reject", { reason });
  }, [approval, approvalFeedback, handleApproval]);

  const submitEditedApproval = useCallback(async () => {
    if (!approval) return;
    try {
      const editedAction = parseEditedActionDraft(approvalEditDraft, approval);
      await handleApproval("edit", {
        reason: approvalFeedback.trim() || undefined,
        editedAction,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid edited approval payload.");
    }
  }, [approval, approvalEditDraft, approvalFeedback, handleApproval]);

  const hasUnsavedChanges = !!selectedPath && fileContent !== savedContent;
  const saveLabel = !selectedPath ? "Open a file to save" : isSaving ? "Saving..." : hasUnsavedChanges ? "Save" : "Saved";
  const hasPromptText = prompt.trim().length > 0;
  const modelOptions = useMemo(() => {
    const configured = (config?.models ?? []).map((model) => model.value);
    return configured.length > 0 ? configured : [...FIREWORKS_MODEL_OPTIONS];
  }, [config]);

  function newTask() {
    const nextIndex = chatThreads.length + 1;
    const id = crypto.randomUUID();
    setChatThreads((current) => [{ id, title: `Chat ${nextIndex}`, runs: [], backendSession: undefined }, ...current]);
    setActiveThreadId(id);
    setAgentTitle(`Chat ${nextIndex}`);
    setPrompt("");
    setImageAttachments([]);
    setShowHistory(false);
    setShowActions(false);
  }

  function clearRunOutput() {
    setLiveRunBlocks([]);
    setShowActions(false);
  }

  async function handleImageSelection(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    await ingestImageFiles(Array.from(files));
    event.target.value = "";
  }

  async function ingestImageFiles(files: File[]) {
    const supportedExtensions = new Set(["png", "jpg", "jpeg", "heic", "heif", "webp", "gif"]);
    const next: ImageAttachment[] = [];
    for (const file of files) {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      const isImageMime = file.type.toLowerCase().startsWith("image/");
      const isSupportedExtension = supportedExtensions.has(extension);
      if (!isImageMime && !isSupportedExtension) continue;
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error(`Unable to read image: ${file.name}`));
        reader.readAsDataURL(file);
      });
      if (dataUrl) {
        next.push({ id: crypto.randomUUID(), name: file.name, dataUrl });
      }
    }
    if (next.length === 0) {
      setError("No supported images found. Use PNG, JPG, JPEG, HEIC, HEIF, WEBP, or GIF.");
      return;
    }
    setImageAttachments((current) => [...current, ...next].slice(0, 6));
  }

  function removeAttachment(id: string) {
    setImageAttachments((current) => current.filter((item) => item.id !== id));
  }

  async function toggleVoiceInput() {
    if (isTranscribingAudio) return;
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      return;
    }
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("Microphone is not available in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaChunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) mediaChunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        setIsRecording(false);
        stream.getTracks().forEach((track) => track.stop());
        const audioBlob = new Blob(mediaChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        mediaChunksRef.current = [];
        if (!audioBlob.size) return;
        setIsTranscribingAudio(true);
        try {
          const result = await transcribeAudio(audioBlob);
          const text = result.text.trim();
          if (text) {
            setPrompt((current) => (current.trim() ? `${current.trim()} ${text}` : text));
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : "Audio transcription failed.");
        } finally {
          setIsTranscribingAudio(false);
        }
      };
      recorder.start();
      setIsRecording(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to access microphone.");
      setIsRecording(false);
    }
  }

  function resetAgentTitle() {
    setAgentTitle("Agents");
    setShowActions(false);
  }

  const toggleTerminal = useCallback(() => {
    if (!terminalPanelRef.current) return;
    if (terminalPanelRef.current.isCollapsed()) {
      terminalPanelRef.current.expand();
      return;
    }
    terminalPanelRef.current.collapse();
  }, [terminalPanelRef]);

  const closeEditorTab = useCallback(() => {
    if (!selectedPath) return;
    if (hasUnsavedChanges) {
      const ok = window.confirm("Discard unsaved changes for this file?");
      if (!ok) return;
    }
    setSelectedPath("");
    setFileContent("");
    setSavedContent("");
  }, [hasUnsavedChanges, selectedPath]);

  const workspaceMissing = workspaces.length === 0 || !session;
  const workspaceBlocked = workspaceIssue !== null;

  const clearAgentTerminal = useCallback(() => {
    setAgentTerminalLines(
      workspaceBlocked
        ? [workspaceIssue?.message ?? "Workspace is blocked."]
        : workspaceMissing
          ? [
              "Welcome to Dynamic Agent Studio.",
              "Create a workspace (center panel) to open the editor, file tree, and agent.",
            ]
          : ["Agent terminal ready."],
    );
  }, [workspaceBlocked, workspaceIssue?.message, workspaceMissing]);

  const clearUserTerminal = useCallback(() => {
    setUserTerminalBuffer(
      workspaceBlocked
        ? `${workspaceIssue?.message ?? "Workspace is blocked."}\n`
        : workspaceMissing
          ? "Open a workspace to start the user terminal.\n"
          : "",
    );
  }, [workspaceBlocked, workspaceIssue?.message, workspaceMissing]);

  const runUserTerminalCommand = useCallback(() => {
    const command = userTerminalCommand.trim();
    const socket = terminalSocketRef.current;
    if (!command || !socket || socket.readyState !== WebSocket.OPEN) return;
    sendTerminalEvent(socket, { type: "input", data: `${command}\n` });
    setUserTerminalCommand("");
  }, [userTerminalCommand]);

  const interruptUserTerminal = useCallback(() => {
    const socket = terminalSocketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    sendTerminalEvent(socket, { type: "interrupt" });
    appendUserTerminalText("^C\n");
  }, [appendUserTerminalText]);

  return (
    <>
      <Dialog.Root open={workspaceModalOpen} onOpenChange={setWorkspaceModalOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="workspace-dialog-overlay" />
          <Dialog.Content className="workspace-dialog-content">
            <Dialog.Title className="workspace-dialog-title">Create workspace</Dialog.Title>
            <Dialog.Description className="workspace-dialog-description">
              Each workspace is an isolated folder with its own README and files.
            </Dialog.Description>
            <div className="workspace-dialog-label">
              <span>Name</span>
              <div className="workspace-dialog-name-row">
                <input className="workspace-dialog-input" value={newWorkspaceName} readOnly />
                <Button type="button" variant="outline" size="sm" onClick={regenerateWorkspaceName}>
                  Regenerate
                </Button>
              </div>
            </div>
            <div className="workspace-dialog-actions">
              <Dialog.Close type="button" className="workspace-dialog-cancel">
                Cancel
              </Dialog.Close>
              <Button type="button" onClick={() => void confirmCreateWorkspace()} disabled={!newWorkspaceName.trim()}>
                Create
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <main className="ide-shell ide-shell-resizable">
        <aside className="activity-bar">
          <button
            type="button"
            className="activity-item"
            title="Hide explorer"
            onClick={() => explorerPanelRef.current?.collapse()}
          >
            <PanelLeftClose />
          </button>
          <button
            type="button"
            className="activity-item"
            title="Show explorer"
            onClick={() => explorerPanelRef.current?.expand()}
          >
            <ChevronRight />
          </button>
          <button type="button" className="activity-item" title="Hide chat" onClick={() => chatPanelRef.current?.collapse()}>
            <ChevronRight />
          </button>
          <button type="button" className="activity-item" title="Show chat" onClick={() => chatPanelRef.current?.expand()}>
            <ChevronLeft />
          </button>
          <div className="activity-logo">
            <Code2 />
          </div>
        </aside>

        <Group
          orientation="horizontal"
          className="ide-panel-group"
          resizeTargetMinimumSize={{ coarse: 22, fine: 12 }}
        >
          <Panel
            id="explorer"
            collapsible
            collapsedSize={0}
            defaultSize="22%"
            minSize="16%"
            maxSize="34%"
            panelRef={explorerPanelRef}
            className="ide-panel-explorer"
          >
            <aside className="explorer-pane explorer-pane-fill">
              <div className="brand-strip">
                <div>
                  <h1>
                    <Link to="/" className="brand-home-link">
                      Dynamic Agent Studio
                    </Link>
                  </h1>
                </div>
                <Button variant="ghost" size="icon" onClick={() => void boot()} title="Refresh">
                  <RefreshCw />
                </Button>
              </div>

              <section className="workspace-switcher">
                <div className="pane-title">
                  <span>Workspaces</span>
                  {workspaces.length > 0 ? (
                    <Button variant="ghost" size="icon" onClick={openWorkspaceModal} title="New workspace">
                      <Plus />
                    </Button>
                  ) : null}
                </div>
                {workspaces.length === 0 ? (
                  <div className="workspace-sidebar-hint">
                    <div className="workspace-sidebar-hint-icon" aria-hidden>
                      <FolderGit2 />
                    </div>
                    <p className="workspace-sidebar-hint-title">No workspace yet</p>
                    <p className="workspace-sidebar-hint-text">Use <strong>Create workspace</strong> in the editor area to get started.</p>
                  </div>
                ) : (
                  <div className="workspace-list">
                    {workspaces.map((workspace) => (
                      <button
                        className={workspace.name === activeWorkspace ? "workspace-item active" : "workspace-item"}
                        key={workspace.name}
                        type="button"
                        onClick={() => void openWorkspace(workspace.name)}
                      >
                        <FolderGit2 />
                        <span>{workspace.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </section>

              <section className="file-pane">
                <div className="pane-title">
                  <span>Files</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => void refreshWorkspace()}
                    title="Refresh files"
                    disabled={!session}
                  >
                    <RefreshCw />
                  </Button>
                </div>
                {workspaceBlocked ? (
                  <WorkspaceIssueCard issue={workspaceIssue} busy={false} onRepair={() => void repairActiveWorkspace()} compact />
                ) : workspaceMissing ? (
                  <div className="file-pane-idle">
                    <p>Files from your workspace will list here.</p>
                  </div>
                ) : (
                  <FileTree node={tree} selectedPath={selectedPath} onSelect={selectFile} />
                )}
              </section>
            </aside>
          </Panel>

          <Separator className="resize-handle" />

          <Panel id="center" defaultSize="50%" minSize="36%" className="ide-panel-center">
            <WorkbenchEditorPane
              selectedPath={selectedPath}
              workspaceBlocked={workspaceBlocked}
              workspaceMissing={workspaceMissing}
              workspaceIssue={workspaceIssue}
              hasUnsavedChanges={hasUnsavedChanges}
              isSaving={isSaving}
              saveLabel={saveLabel}
              editorLanguage={editorLanguage}
              fileContent={fileContent}
              onFileContentChange={setFileContent}
              onCloseFile={closeEditorTab}
              onSaveFile={saveFile}
              onRepairWorkspace={repairActiveWorkspace}
              onOpenWorkspaceModal={openWorkspaceModal}
              activeTerminalTab={activeTerminalTab}
              agentTerminalLines={agentTerminalLines}
              agentTerminalOutputRef={agentTerminalOutputRef}
              userTerminalOutputRef={userTerminalOutputRef}
              renderedUserTerminalHtml={renderedUserTerminalHtml}
              userTerminalPromptLabel={userTerminalPromptLabel}
              userTerminalCommand={userTerminalCommand}
              userTerminalConnected={userTerminalConnected}
              terminalPanelRef={terminalPanelRef}
              onActiveTerminalTabChange={setActiveTerminalTab}
              onClearAgentTerminal={clearAgentTerminal}
              onClearUserTerminal={clearUserTerminal}
              onUserTerminalCommandChange={setUserTerminalCommand}
              onRunUserTerminalCommand={runUserTerminalCommand}
              onInterruptUserTerminal={interruptUserTerminal}
              onToggleTerminal={toggleTerminal}
            />
          </Panel>

          <Separator className="resize-handle" />

          <Panel
            id="chat"
            collapsible
            collapsedSize={0}
            defaultSize="28%"
            minSize="22%"
            maxSize="40%"
            panelRef={chatPanelRef}
            className="ide-panel-chat"
          >
            <aside className="agent-chat-pane agent-chat-pane-fill">
        <div className="agent-pane-header">
          <div className="agent-pane-title">
            <div className="chat-tabs-top">
              {chatThreads.map((thread, index) => (
                <div className="chat-tab-top-wrap" key={thread.id}>
                  <button
                    type="button"
                    className={thread.id === activeThreadId ? "chat-tab-top active" : "chat-tab-top"}
                    onClick={() => {
                      setActiveThreadId(thread.id);
                      setAgentTitle(thread.title);
                      if (thread.backendSession) setSession(thread.backendSession);
                    }}
                    title={thread.title}
                  >
                    {thread.title}
                  </button>
                  {index < chatThreads.length - 1 && <span className="chat-tab-divider">/</span>}
                </div>
              ))}
            </div>
          </div>
          <div className="agent-pane-actions" aria-label="Agent panel actions">
            <button className="pane-icon-button" type="button" title="New task" onClick={newTask}>
              <Plus />
            </button>
            <button className="pane-icon-button" type="button" title="Recent runs" onClick={() => setShowHistory((v) => !v)}>
              <History />
            </button>
            <button className="pane-icon-button" type="button" title="More actions" onClick={() => setShowActions((v) => !v)}>
              <MoreHorizontal />
            </button>
            <button className="pane-icon-button" type="button" title="Clear output" onClick={clearRunOutput}>
              <X />
            </button>
          </div>
          {showHistory && (
            <div className="agent-flyout history-flyout">
              {chatThreads.length ? (
                chatThreads.map((thread) => (
                  <button
                    key={thread.id}
                    className="agent-flyout-item"
                    type="button"
                    onClick={() => {
                      setActiveThreadId(thread.id);
                      setAgentTitle(thread.title);
                      if (thread.backendSession) setSession(thread.backendSession);
                      setShowHistory(false);
                    }}
                  >
                    {thread.title}
                  </button>
                ))
              ) : (
                <p className="agent-flyout-empty">No recent prompts yet.</p>
              )}
            </div>
          )}
          {showActions && (
            <div className="agent-flyout actions-flyout">
              <button className="agent-flyout-item" type="button" onClick={newTask}>
                New Task
              </button>
              <button className="agent-flyout-item" type="button" onClick={clearRunOutput}>
                Clear Output
              </button>
              <button className="agent-flyout-item" type="button" onClick={resetAgentTitle}>
                Reset Title
              </button>
            </div>
          )}
        </div>

        <div className="agent-pane-body">
          <div className="agent-stage">
            <div className="agent-timeline" ref={chatPaneRef}>
              <AgentRunTimeline
                runs={activeThread?.runs ?? []}
                lastSubmittedPrompt={lastSubmittedPrompt}
                liveRunBlocks={liveRunBlocks}
                isRunning={isRunning}
                approval={approval}
                pendingApprovalsCount={pendingApprovals.length}
                approvalFeedback={approvalFeedback}
                approvalEditDraft={approvalEditDraft}
                approvalEditMode={approvalEditMode}
                isDecidingApproval={isDecidingApproval}
                onFeedbackChange={setApprovalFeedback}
                onEditDraftChange={setApprovalEditDraft}
                onToggleEditMode={setApprovalEditMode}
                onReject={rejectCurrentApproval}
                onApprove={approveCurrentApproval}
                onSubmitEdit={submitEditedApproval}
              />
            </div>

            <section className={cn("agent-composer", (workspaceMissing || workspaceBlocked) && "agent-composer-idle")}>
              <input
                ref={imageInputRef}
                type="file"
                accept=".png,.jpg,.jpeg,.heic,.heif,.webp,.gif,image/png,image/jpeg,image/heic,image/heif,image/webp,image/gif"
                multiple
                className="hidden"
                onChange={(event) => void handleImageSelection(event)}
              />
              {imageAttachments.length > 0 && (
                <div className="composer-attachments" aria-label="Selected images">
                  {imageAttachments.map((attachment) => (
                    <div key={attachment.id} className="composer-attachment-chip">
                      <img src={attachment.dataUrl} alt={attachment.name} />
                      <button type="button" onClick={() => removeAttachment(attachment.id)} aria-label={`Remove ${attachment.name}`}>
                        <X />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <Textarea
                ref={composerTextareaRef}
                className="agent-textarea min-h-[52px]! border-0 bg-transparent px-0 py-0 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
                value={prompt}
                onChange={(event) => {
                  setPrompt(event.target.value);
                  queueMicrotask(resizeComposerTextarea);
                }}
                placeholder={
                  workspaceBlocked
                    ? "Repair the workspace before chatting with the agent…"
                    : workspaceMissing
                      ? "Create a workspace to start chatting with the agent…"
                      : "Ask anything, @ to mention, / for workflows..."
                }
                readOnly={workspaceMissing || workspaceBlocked}
                rows={1}
                onPaste={(event) => {
                  const clipboardFiles = Array.from(event.clipboardData?.files ?? []);
                  if (!clipboardFiles.length) return;
                  const hasImage = clipboardFiles.some(
                    (file) =>
                      file.type.toLowerCase().startsWith("image/") ||
                      ["png", "jpg", "jpeg", "heic", "heif", "webp", "gif"].includes(
                        file.name.split(".").pop()?.toLowerCase() ?? "",
                      ),
                  );
                  if (!hasImage) return;
                  event.preventDefault();
                  void ingestImageFiles(clipboardFiles);
                }}
              />
              <div className="agent-composer-footer">
                <div className="agent-composer-tools">
                  <button
                    className="composer-icon-button"
                    type="button"
                    title="Add images"
                    onClick={() => imageInputRef.current?.click()}
                  >
                    <Plus />
                  </button>
                  <div className="model-picker">
                    <button
                      className="agent-model-pill"
                      type="button"
                      title="Select model"
                      onClick={() => setShowModelMenu((v) => !v)}
                    >
                      <span>{formatModelLabel(selectedModel || config?.defaultModel)}</span>
                      <ChevronDown />
                    </button>
                    {showModelMenu && (
                      <div className="model-menu" role="menu" aria-label="Model selector">
                        {modelOptions.map((model) => (
                          <button
                            key={model}
                            type="button"
                            className={model === (selectedModel || config?.defaultModel) ? "model-menu-item active" : "model-menu-item"}
                            onClick={() => {
                              setSelectedModel(model);
                              setShowModelMenu(false);
                            }}
                          >
                            {formatModelLabel(model)}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="model-picker">
                    <button
                      className="agent-model-pill"
                      type="button"
                      title="Select agent permission mode"
                      onClick={() => setShowModeMenu((v) => !v)}
                    >
                      <span>{formatModeLabel(selectedMode)}</span>
                      <ChevronDown />
                    </button>
                    {showModeMenu && (
                      <div className="model-menu" role="menu" aria-label="Mode selector">
                        {(config?.modes ?? [
                          { id: "ask_before_edits", name: "Ask before edits" },
                          { id: "accept_edits", name: "Accept edits, ask execute" },
                          { id: "accept_everything", name: "Accept everything" },
                        ]).map((mode) => (
                          <button
                            key={mode.id}
                            type="button"
                            className={mode.id === selectedMode ? "model-menu-item active" : "model-menu-item"}
                            onClick={() => {
                              setSelectedMode(mode.id);
                              setShowModeMenu(false);
                            }}
                          >
                            {mode.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <button
                  className="composer-primary-button"
                  type="button"
                  disabled={isRunning || workspaceMissing || workspaceBlocked || isTranscribingAudio}
                  onClick={() => {
                    if (hasPromptText || imageAttachments.length > 0) {
                      void runAgent();
                      return;
                    }
                    void toggleVoiceInput();
                  }}
                  title={
                    isRunning
                      ? "Running..."
                      : isTranscribingAudio
                        ? "Transcribing..."
                        : hasPromptText || imageAttachments.length > 0
                          ? "Send"
                          : isRecording
                            ? "Stop recording"
                            : "Voice"
                  }
                >
                  {hasPromptText || imageAttachments.length > 0 ? <ArrowUp /> : isRecording ? <Square /> : <Mic />}
                </button>
              </div>
            </section>

            <p className="agent-footnote">AI may make mistakes. Double-check all generated code.</p>
          </div>
        </div>

      </aside>
          </Panel>
        </Group>

    </main>
    </>
  );
}

type CheckpointPhase = "architecture_review" | "pre_publish_review" | "post_publish_review";

type CheckpointReviewData = {
  phase: CheckpointPhase;
  summary: string;
  findings: string[];
  nextSteps: string[];
  commands: string[];
  files: string[];
  questionsForHuman: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => (typeof item === "string" && item.trim() ? [item.trim()] : []));
}

function isCheckpointApproval(approval: ApprovalData | null): approval is ApprovalData {
  return Boolean(approval && approval.tool === "request_checkpoint_review");
}

function readCheckpointReviewData(approval: ApprovalData | null): CheckpointReviewData | null {
  if (!isCheckpointApproval(approval)) return null;
  const payload = isRecord(approval.payload) ? approval.payload : {};
  const phase = readString(payload.phase);
  if (phase !== "architecture_review" && phase !== "pre_publish_review" && phase !== "post_publish_review") {
    return null;
  }
  return {
    phase,
    summary: readString(payload.summary),
    findings: readStringArray(payload.findings),
    nextSteps: readStringArray(payload.next_steps),
    commands: readStringArray(payload.commands),
    files: readStringArray(payload.files),
    questionsForHuman: readStringArray(payload.questions_for_human),
  };
}

function approvalCheckpointLabel(approval: ApprovalData | null): string {
  return readCheckpointReviewData(approval)?.phase ?? "";
}

function formatCheckpointPhase(phase: string): string {
  return phase
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function defaultEditedActionDraft(approval: ApprovalData | null): string {
  if (!approval) return "";
  return JSON.stringify({ name: approval.tool, args: approval.payload }, null, 2);
}

function defaultRejectReason(approval: ApprovalData | null): string {
  const checkpoint = readCheckpointReviewData(approval);
  if (checkpoint) {
    return `Please revise the ${formatCheckpointPhase(checkpoint.phase)} checkpoint and wait for another review.`;
  }
  return approval ? `User rejected ${approval.tool}.` : "User rejected this action.";
}

function parseEditedActionDraft(text: string, approval: ApprovalData): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("Edited approval payload must be valid JSON.");
  }
  if (!isRecord(parsed)) {
    throw new Error("Edited approval payload must be a JSON object.");
  }
  const maybeName = readString(parsed.name);
  const maybeArgs = parsed.args;
  if (maybeName) {
    if (!isRecord(maybeArgs)) {
      throw new Error("Edited approval payload must include an object `args` field.");
    }
    return { name: maybeName, args: maybeArgs };
  }
  return { name: approval.tool, args: parsed };
}

function terminalLineForEvent(event: StreamEvent): string | null {
  if (event.type === "custom" || event.type === "update") return null;
  if (event.type === "todo") {
    const items = readTodoItems(event.data.items);
    if (!items.length) return "[todo] updated";
    return `[todo] ${items.map((item) => `${item.status}: ${item.text}`).join(" | ")}`;
  }
  if (event.type === "subagent") {
    const name = readString(event.data.name) || prettifySpecialistLabel(event.source);
    const status = readString(event.data.status);
    const summary = event.message || readString(event.data.summary);
    const suffix = [status, summary].filter(Boolean).join(" · ");
    return suffix ? `[subagent] ${name}: ${suffix}` : `[subagent] ${name}`;
  }
  if (event.type === "thinking") {
    return `[thinking] ${event.message || ""}`;
  }
  if (event.type === "tool_call") {
    const name = readString(event.data.name) || "tool";
    const args = event.data.args;
    const result = readString(event.data.result);
    const command = typeof args === "object" && args && "command" in args ? String((args as { command: unknown }).command) : "";
    if (name === "execute" || command) {
      return result ? `$ ${command}\n${result}` : `$ ${command || name}`;
    }
    return result ? `[tool] ${name}\n${result}` : `[tool] ${name} ${formatData(args)}`;
  }
  if (event.type === "approval_required") {
    const tool = readString(event.data.tool) || "tool";
    return `[approval required] ${approvalSummaryFromData(tool, event.data.payload)}`;
  }
  if (event.type === "blocked_command") {
    return `[blocked] ${event.message || formatData(event.data)}`;
  }
  if (event.type === "file_change") {
    return `[file] ${event.message || formatData(event.data)}`;
  }
  if (event.type === "error") {
    return `[error] ${event.message || formatData(event.data)}`;
  }
  if (event.type === "done") {
    return "[done] agent run complete";
  }
  return null;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function formatData(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function isWorkspaceHealth(value: unknown): value is WorkspaceHealth {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<WorkspaceHealth>;
  return (
    (candidate.status === "valid" || candidate.status === "invalid") &&
    typeof candidate.message === "string" &&
    Array.isArray(candidate.invalidEntries)
  );
}

function workspaceIssueFromError(error: unknown): WorkspaceHealth | null {
  if (error instanceof ApiError && isWorkspaceHealth(error.detail)) {
    return error.detail;
  }
  return null;
}

export function readApprovalCommand(approval: ApprovalData | null): string {
  if (!approval) return "";
  const payload = approval.payload;
  if (typeof payload !== "object" || !payload) return "";
  if ("command" in payload) return String((payload as { command: unknown }).command ?? "");
  if ("cmd" in payload) return String((payload as { cmd: unknown }).cmd ?? "");
  return "";
}

function approvalSummaryForCard(approval: ApprovalData | null): string {
  if (!approval) return "Review and approve to continue.";
  const checkpoint = readCheckpointReviewData(approval);
  if (checkpoint) {
    if (checkpoint.summary) return checkpoint.summary;
    return `Review ${formatCheckpointPhase(checkpoint.phase)} before continuing.`;
  }
  const command = readApprovalCommand(approval).replace(/\s+/g, " ").trim();
  if (command) {
    return command.length > 120 ? `${command.slice(0, 117)}...` : command;
  }
  return "This action needs approval before the run can continue.";
}

export function appendRunBlock(blocks: RunBlock[], next: RunBlock): RunBlock[] {
  const last = blocks[blocks.length - 1];
  if (!last || last.kind !== next.kind) {
    return [...blocks, next];
  }
  const joiner = shouldUseSoftJoin(last.kind, last.text, next.text) ? " " : "\n";
  return [
    ...blocks.slice(0, -1),
    {
      ...last,
      text: `${last.text}${joiner}${next.text}`.trim(),
      eventType: next.eventType ?? last.eventType,
    },
  ];
}

function shouldUseSoftJoin(kind: RunBlockKind, left: string, right: string): boolean {
  if (kind === "assistant") return false;
  if (kind === "thinking") {
    return !left.includes("\n") && !right.includes("\n");
  }
  return false;
}

export function appendAssistantToken(blocks: RunBlock[], token: string): RunBlock[] {
  const last = blocks[blocks.length - 1];
  if (last?.kind === "assistant") {
    return [...blocks.slice(0, -1), { ...last, text: `${last.text}${token}` }];
  }
  return [...blocks, { id: crypto.randomUUID(), kind: "assistant", text: token, eventType: "token" }];
}

export function getLatestAssistantText(blocks: RunBlock[]): string {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    if (blocks[index].kind === "assistant") return blocks[index].text;
  }
  return "";
}

function getAssistantTranscript(blocks: RunBlock[]): string {
  return blocks
    .filter((block) => block.kind === "assistant")
    .map((block) => block.text)
    .join("\n\n")
    .trim();
}

export function mapEventToRunBlock(event: StreamEvent): RunBlock | null {
  if (event.type === "todo") {
    return null;
  }
  if (event.type === "subagent") {
    const name = readString(event.data.name) || prettifySpecialistLabel(event.source);
    const status = readString(event.data.status);
    const summary = event.message || readString(event.data.summary);
    return {
      id: crypto.randomUUID(),
      kind: "subagent",
      text: [name, status, summary].filter(Boolean).join(" · "),
      eventType: "subagent",
    };
  }
  if (event.type === "thinking") {
    const text = (event.message || "").replace(/\s+/g, " ").trim();
    if (!text || /^graph update$/i.test(text)) return null;
    return { id: crypto.randomUUID(), kind: "thinking", text, eventType: "thinking" };
  }
  if (event.type === "tool_call") {
    return { id: crypto.randomUUID(), kind: "tool", text: summarizeToolBlock(event), eventType: "tool_call" };
  }
  if (event.type === "approval_required") {
    const tool = readString(event.data.tool) || "tool";
    return {
      id: crypto.randomUUID(),
      kind: "approval",
      text: `Approval required: ${approvalSummaryFromData(tool, event.data.payload)}`,
      eventType: "approval_required",
    };
  }
  if (event.type === "blocked_command") {
    return {
      id: crypto.randomUUID(),
      kind: "error",
      text: event.message || "Blocked command",
      eventType: "blocked_command",
    };
  }
  if (event.type === "file_change") {
    return null;
  }
  if (event.type === "error") {
    return {
      id: crypto.randomUUID(),
      kind: "error",
      text: event.message || formatData(event.data) || "Agent error",
      eventType: "error",
    };
  }
  if (event.type === "custom" || event.type === "update" || event.type === "done" || event.type === "token") return null;
  return null;
}

function renderMarkdownText(text: string) {
  return (
    <div className="timeline-rich-text markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p>{children}</p>,
          pre: ({ children }) => <pre>{children}</pre>,
          code: (props) => {
            const { children, className } = props;
            const inline = Boolean((props as { inline?: boolean }).inline);
            return inline ? (
              <code className={`inline-code ${className ?? ""}`.trim()}>{children}</code>
            ) : (
              <code className={className}>{children}</code>
            );
          },
          table: ({ children }) => <table>{children}</table>,
          thead: ({ children }) => <thead>{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr>{children}</tr>,
          th: ({ children }) => <th>{children}</th>,
          td: ({ children }) => <td>{children}</td>,
          ul: ({ children }) => <ul>{children}</ul>,
          ol: ({ children }) => <ol>{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
          h1: ({ children }) => <h1>{children}</h1>,
          h2: ({ children }) => <h2>{children}</h2>,
          h3: ({ children }) => <h3>{children}</h3>,
          blockquote: ({ children }) => <blockquote>{children}</blockquote>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function renderPlainText(text: string) {
  return (
    <div className="timeline-plain-text">
      <p>{text}</p>
    </div>
  );
}

function renderPreformattedText(text: string) {
  return (
    <div className="timeline-plain-text">
      <pre>{text}</pre>
    </div>
  );
}

function renderRunBlock(block: RunBlock) {
  if (block.kind === "assistant") {
    return (
      <article className="timeline-card assistant" key={block.id}>
        {renderMarkdownText(block.text)}
      </article>
    );
  }
  if (block.kind === "tool") {
    return (
      <article className="timeline-card tool" key={block.id}>
        {renderPreformattedText(block.text)}
      </article>
    );
  }
  if (block.kind === "error") {
    return (
      <article className="timeline-card error" key={block.id}>
        {renderPreformattedText(block.text)}
      </article>
    );
  }
  return (
    <article className={`timeline-card ${block.kind}`} key={block.id}>
      {renderPlainText(block.text)}
    </article>
  );
}

function readTodoItems(value: unknown): TodoItem[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const maybe = item as Partial<TodoItem>;
    if (
      typeof maybe.id !== "string" ||
      typeof maybe.text !== "string" ||
      (maybe.status !== "pending" && maybe.status !== "active" && maybe.status !== "completed")
    ) {
      return [];
    }
    return [{ id: maybe.id, text: maybe.text, status: maybe.status }];
  });
}

function prettifySpecialistLabel(source: string): string {
  return source
    .replace(/^tools:/, "")
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function summarizeTraceEvent(event: StreamEvent): string {
  if (event.type === "subagent") {
    return summarizeSubagentEvent(event);
  }
  if (event.type === "tool_call") {
    return summarizeToolEvent(event);
  }
  if (event.type === "file_change") return event.message || "File changed";
  if (event.type === "approval_required") return approvalSummaryForEvent(event);
  if (event.type === "todo") {
    const items = readTodoItems(event.data.items);
    const active = items.find((item) => item.status === "active");
    if (active) return `Active: ${active.text}`;
    return items.map((item) => `${item.status}: ${item.text}`).join(" | ");
  }
  if (event.type === "update") return event.message || "Run updated";
  if (event.type === "error") return event.message || "Run error";
  return event.message || "";
}

function approvalSummaryForEvent(event: StreamEvent): string {
  const tool = readString(event.data.tool) || "tool";
  return approvalSummaryFromData(tool, event.data.payload);
}

function approvalSummaryFromData(tool: string, payload: unknown): string {
  if (tool === "request_checkpoint_review" && isRecord(payload)) {
    const phase = readString(payload.phase);
    const summary = readString(payload.summary);
    const label = phase ? formatCheckpointPhase(phase) : "Checkpoint review";
    return summary ? `${label}: ${summary}` : label;
  }
  const command =
    isRecord(payload) && "command" in payload
      ? String(payload.command ?? "")
      : isRecord(payload) && "cmd" in payload
        ? String(payload.cmd ?? "")
        : "";
  return command ? `${tool}: ${command}` : tool;
}

function summarizeToolEvent(event: StreamEvent): string {
  const name = readString(event.data.name) || "tool";
  const args = isRecord(event.data.args) ? event.data.args : {};
  const command = readString(args.command);
  const result = readString(event.data.result).trim();
  if (command && result) {
    const compact = result.replace(/\s+/g, " ").trim();
    return `${command} -> ${compact.length > 120 ? `${compact.slice(0, 117)}...` : compact}`;
  }
  if (command) return command;
  if (result) return `${name} -> ${result.length > 120 ? `${result.slice(0, 117)}...` : result}`;
  return name;
}

function summarizeSubagentEvent(event: StreamEvent): string {
  const status = readString(event.data.status);
  const summary = event.message || readString(event.data.summary);
  return [status, summary].filter(Boolean).join(" · ");
}

function summarizeToolBlock(event: StreamEvent): string {
  const name = readString(event.data.name) || "tool";
  const args = isRecord(event.data.args) ? event.data.args : {};
  const command = readString(args.command);
  const result = readString(event.data.result).trim();
  if (command && result) return `$ ${command}\n${result}`;
  if (command) return `$ ${command}`;
  if (result) return `${name}\n${result}`;
  return name;
}

function WorkspaceIssueCard({
  issue,
  busy,
  onRepair,
  compact = false,
}: {
  issue: WorkspaceHealth | null;
  busy: boolean;
  onRepair: () => void;
  compact?: boolean;
}) {
  if (!issue) return null;
  return (
    <div className={compact ? "file-pane-idle" : "workbench-empty-canvas"}>
      {!compact ? <p className="workbench-empty-kicker">Workspace repair</p> : null}
      <h2 className={compact ? "workspace-sidebar-hint-title" : "workbench-empty-heading"}>
        {issue.repairAvailable ? "Workspace needs repair" : "Workspace blocked"}
      </h2>
      <p className={compact ? "workspace-sidebar-hint-text" : "workbench-empty-lead"}>{issue.message}</p>
      {issue.invalidEntries.length > 0 ? (
        <div className="timeline-plain-text">
          <p>
            Invalid entries: <strong>{issue.invalidEntries.join(", ")}</strong>
          </p>
        </div>
      ) : null}
      {issue.repairAvailable ? (
        <Button type="button" size="default" className={compact ? undefined : "workbench-empty-cta"} onClick={onRepair} disabled={busy}>
          {busy ? "Repairing..." : "Repair workspace"}
        </Button>
      ) : null}
    </div>
  );
}

function ApprovalReviewCard({
  approval,
  pendingCount,
  feedback,
  editDraft,
  editMode,
  busy,
  onFeedbackChange,
  onEditDraftChange,
  onToggleEditMode,
  onReject,
  onApprove,
  onSubmitEdit,
}: {
  approval: ApprovalData;
  pendingCount: number;
  feedback: string;
  editDraft: string;
  editMode: boolean;
  busy: boolean;
  onFeedbackChange: (value: string) => void;
  onEditDraftChange: (value: string) => void;
  onToggleEditMode: (value: boolean) => void;
  onReject: () => void;
  onApprove: () => void;
  onSubmitEdit: () => void;
}) {
  const checkpoint = readCheckpointReviewData(approval);
  const allowedDecisions = approval.allowedDecisions ?? ["approve", "reject"];
  const editAllowed = allowedDecisions.includes("edit");
  const queueRemainder = Math.max(0, pendingCount - 1);

  return (
    <article className="timeline-card system approval-inline-card">
      <div className="approval-header">
        <div>
          <p className="approval-meta-line">
            <span>
              Tool: <strong>{approval.tool}</strong>
            </span>
            {checkpoint?.phase ? (
              <span className="approval-phase-chip">{formatCheckpointPhase(checkpoint.phase)}</span>
            ) : null}
          </p>
          <p className="approval-command-preview">{approvalSummaryForCard(approval)}</p>
        </div>
        {queueRemainder > 0 ? <span className="approval-queue-chip">{queueRemainder} queued</span> : null}
      </div>

      {checkpoint ? (
        <div className="approval-checkpoint-sections">
          {checkpoint.findings.length > 0 ? (
            <ApprovalSection title="Findings" items={checkpoint.findings} />
          ) : null}
          {checkpoint.nextSteps.length > 0 ? (
            <ApprovalSection title="Next steps" items={checkpoint.nextSteps} />
          ) : null}
          {checkpoint.commands.length > 0 ? (
            <ApprovalSection title="Commands" items={checkpoint.commands} monospace />
          ) : null}
          {checkpoint.files.length > 0 ? <ApprovalSection title="Files" items={checkpoint.files} monospace /> : null}
          {checkpoint.questionsForHuman.length > 0 ? (
            <ApprovalSection title="Questions for you" items={checkpoint.questionsForHuman} />
          ) : null}
        </div>
      ) : (
        <details className="approval-payload-details">
          <summary>Review payload</summary>
          <pre>{JSON.stringify(approval.payload, null, 2)}</pre>
        </details>
      )}

      <label className="approval-feedback-block">
        <span>{checkpoint ? "Reviewer notes" : "Reason"}</span>
        <Textarea
          value={feedback}
          onChange={(event) => onFeedbackChange(event.target.value)}
          placeholder={
            checkpoint
              ? "Optional note for approval, or explain what should change before the next phase."
              : "Optional reason for approval or rejection."
          }
          className="approval-feedback-textarea"
          rows={3}
        />
      </label>

      {editAllowed ? (
        <div className="approval-edit-shell">
          {!editMode ? (
            <Button variant="outline" disabled={busy} onClick={() => onToggleEditMode(true)}>
              Edit payload
            </Button>
          ) : (
            <>
              <label className="approval-feedback-block">
                <span>Edited tool payload</span>
                <Textarea
                  value={editDraft}
                  onChange={(event) => onEditDraftChange(event.target.value)}
                  className="approval-json-textarea"
                  rows={10}
                />
              </label>
              <div className="approval-actions approval-actions-secondary">
                <Button variant="outline" disabled={busy} onClick={() => onToggleEditMode(false)}>
                  Cancel edit
                </Button>
                <Button variant="outline" disabled={busy} onClick={onSubmitEdit}>
                  Submit edit
                </Button>
              </div>
            </>
          )}
        </div>
      ) : null}

      <div className="approval-actions">
        <Button variant="outline" disabled={busy} onClick={onReject}>
          {checkpoint ? "Request changes" : "Reject"}
        </Button>
        <Button disabled={busy} onClick={onApprove}>
          <Check data-icon="inline-start" />
          {checkpoint ? "Approve checkpoint" : "Approve"}
        </Button>
      </div>
    </article>
  );
}

function ApprovalSection({
  title,
  items,
  monospace = false,
}: {
  title: string;
  items: string[];
  monospace?: boolean;
}) {
  return (
    <section className="approval-section">
      <h4>{title}</h4>
      <ul className={monospace ? "approval-mono-list" : ""}>
        {items.map((item) => (
          <li key={`${title}-${item}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

export function extractRunBlocksFromAssistantText(text: string): RunBlock[] {
  const blocks: RunBlock[] = [];
  const ranges: Array<{ start: number; end: number; block: RunBlock }> = [];
  const thinkRe = /<think[^>]*>([\s\S]*?)<\/think>/gi;
  const fenceRe = /```[a-zA-Z0-9_-]*\n([\s\S]*?)```/g;
  const cmdLineRe =
    /^\s*(?:\$|>)?\s*(ls|pwd|cd|cat|sed|awk|grep|find|rm|cp|mv|mkdir|chmod|chown|git|npm|pnpm|yarn|python|pytest|make|curl|wget|docker|docker-compose|kubectl)\b/m;

  let match: RegExpExecArray | null;
  while ((match = thinkRe.exec(text)) !== null) {
    const thought = (match[1] || "").trim();
    if (!thought) continue;
    ranges.push({
      start: match.index,
      end: match.index + match[0].length,
      block: { id: crypto.randomUUID(), kind: "thinking", text: thought, eventType: "fallback_assistant" },
    });
  }
  while ((match = fenceRe.exec(text)) !== null) {
    const code = (match[1] || "").trimEnd();
    if (!code || !cmdLineRe.test(code)) continue;
    ranges.push({
      start: match.index,
      end: match.index + match[0].length,
      block: { id: crypto.randomUUID(), kind: "tool", text: code, eventType: "fallback_assistant" },
    });
  }

  ranges.sort((a, b) => a.start - b.start);
  let cursor = 0;
  for (const range of ranges) {
    if (range.start > cursor) {
      const assistantText = text.slice(cursor, range.start).trim();
      if (assistantText) {
        blocks.push({ id: crypto.randomUUID(), kind: "assistant", text: assistantText, eventType: "fallback_assistant" });
      }
    }
    blocks.push(range.block);
    cursor = range.end;
  }
  const tail = text.slice(cursor).trim();
  if (tail) {
    blocks.push({ id: crypto.randomUUID(), kind: "assistant", text: tail, eventType: "fallback_assistant" });
  }
  return blocks.length ? blocks : [{ id: crypto.randomUUID(), kind: "assistant", text, eventType: "fallback_assistant" }];
}

function formatModelLabel(model: string | undefined): string {
  if (!model) return "Loading model";
  const normalized = model.toLowerCase();
  if (normalized.includes("minimax-m2")) return "Minimax m2";
  if (normalized.includes("qwen3p6-plus")) return "Qwen3.6 plus";
  if (normalized.includes("kimi-k2-thinking")) return "Kimi k2 thinking";
  if (normalized.includes("glm-4p7")) return "Glm 4.7";
  const slashPart = model.split("/").pop() || model;
  const cleaned = slashPart.replace(/^models[:/-]?/i, "").trim();
  return cleaned ? `${cleaned.charAt(0).toUpperCase()}${cleaned.slice(1)}` : "Model";
}

export function formatModeLabel(mode: SessionMode): string {
  if (mode === "ask_before_edits") return "Ask before edits";
  if (mode === "accept_everything") return "Accept everything";
  return "Accept edits";
}

function deriveAgentTitle(prompt: string): string {
  const cleaned = prompt.replace(/\s+/g, " ").trim();
  if (!cleaned) return "Chat";
  const normalized = cleaned
    .toLowerCase()
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const stop = new Set([
    "the",
    "a",
    "an",
    "to",
    "for",
    "of",
    "and",
    "or",
    "in",
    "on",
    "at",
    "with",
    "from",
    "about",
    "please",
    "can",
    "you",
    "i",
    "me",
    "my",
    "is",
    "are",
    "this",
    "that",
    "it",
    "we",
    "us",
  ]);
  const keywords = normalized
    .split(" ")
    .filter((w) => w.length > 2 && !stop.has(w))
    .slice(0, 4);
  const base = (keywords.length ? keywords : normalized.split(" ").slice(0, 4))
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
  return base.length > 34 ? `${base.slice(0, 34).trim()}...` : base;
}
