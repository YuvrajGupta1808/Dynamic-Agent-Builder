import Editor from "@monaco-editor/react";
import {
  ArrowUp,
  Check,
  ChevronDown,
  Code2,
  FilePlus2,
  FolderGit2,
  History,
  Mic,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Save,
  SquareTerminal,
  X
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";

import { FileTree } from "./components/FileTree";
import { Button } from "./components/ui/button";
import { Textarea } from "./components/ui/textarea";
import {
  applyFile,
  createSession,
  createWorkspace,
  decideInterrupt,
  getConfig,
  getFileContent,
  getFileTree,
  getWorkspaces,
  streamRun,
} from "./lib/api";
import type {
  AppConfig,
  ApprovalData,
  FileTreeNode,
  SessionRecord,
  StreamEvent,
  WorkspaceSummary,
} from "./types/api";

export function App() {
  const FIREWORKS_MODEL_OPTIONS = ["openai:accounts/fireworks/models/qwen3p6-plus"] as const;
  type ThinkingItem = {
    id: string;
    kind: "tool" | "thinking" | "error";
    text: string;
  };
  type CompletedRun = {
    id: string;
    prompt: string;
    thinkingItems: ThinkingItem[];
    finalOutput: string;
  };
  type ChatThread = {
    id: string;
    title: string;
    runs: CompletedRun[];
    /** Backend session id + metadata; one per UI chat, lazy-created on first send. */
    backendSession?: SessionRecord | null;
  };

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWorkspace, setActiveWorkspace] = useState<string>("default");
  const [session, setSession] = useState<SessionRecord | null>(null);
  const [tree, setTree] = useState<FileTreeNode | null>(null);
  const [selectedPath, setSelectedPath] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [terminalLines, setTerminalLines] = useState<string[]>(["Agents terminal ready."]);
  const [prompt, setPrompt] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [approval, setApproval] = useState<ApprovalData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [thinkingItems, setThinkingItems] = useState<ThinkingItem[]>([]);
  const [lastSubmittedPrompt, setLastSubmittedPrompt] = useState("");
  const [finalOutput, setFinalOutput] = useState("");
  const [streamingAssistantText, setStreamingAssistantText] = useState("");
  const [agentTitle, setAgentTitle] = useState("Agents");
  const [selectedModel, setSelectedModel] = useState<string>("openai:accounts/fireworks/models/qwen3p6-plus");
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [recentPrompts, setRecentPrompts] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showActions, setShowActions] = useState(false);
  const [chatThreads, setChatThreads] = useState<ChatThread[]>([{ id: crypto.randomUUID(), title: "Agents", runs: [] }]);
  const [activeThreadId, setActiveThreadId] = useState<string>("");
  const activeThread = chatThreads.find((thread) => thread.id === activeThreadId) ?? chatThreads[0];
  const streamBufferRef = useRef("");
  const structuredEventsSeenRef = useRef(false);
  const backendFailureRef = useRef(false);
  const lastDerivedThinkingKeyRef = useRef("");
  const runInFlightRef = useRef(false);
  const didBootRef = useRef(false);
  const chatPaneRef = useRef<HTMLDivElement>(null);
  const terminalOutputRef = useRef<HTMLPreElement>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement>(null);

  const COMPOSER_TEXTAREA_MAX_PX = 320;

  const resizeComposerTextarea = useCallback(() => {
    const ta = composerTextareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, COMPOSER_TEXTAREA_MAX_PX)}px`;
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
      const el = terminalOutputRef.current;
      if (!el) return;
      el.scrollTop = el.scrollHeight;
    });
  }, []);

  useEffect(() => {
    if (didBootRef.current) return;
    didBootRef.current = true;
    void boot();
  }, []);

  useEffect(() => {
    if (!activeThreadId && chatThreads.length) {
      setActiveThreadId(chatThreads[0].id);
    }
  }, [activeThreadId, chatThreads]);

  useLayoutEffect(() => {
    resizeComposerTextarea();
  }, [prompt, resizeComposerTextarea]);

  useLayoutEffect(() => {
    scrollChatToBottom();
  }, [
    scrollChatToBottom,
    thinkingItems,
    streamingAssistantText,
    finalOutput,
    lastSubmittedPrompt,
    isRunning,
    activeThreadId,
    activeThread?.runs.length,
  ]);

  useLayoutEffect(() => {
    scrollTerminalToBottom();
  }, [scrollTerminalToBottom, terminalLines]);

  const editorLanguage = useMemo(() => {
    if (selectedPath.endsWith(".py")) return "python";
    if (selectedPath.endsWith(".ts") || selectedPath.endsWith(".tsx")) return "typescript";
    if (selectedPath.endsWith(".json")) return "json";
    if (selectedPath.endsWith(".css")) return "css";
    if (selectedPath.endsWith(".html")) return "html";
    return "markdown";
  }, [selectedPath]);

  async function boot() {
    try {
      const nextConfig = await getConfig();
      setConfig(nextConfig);
      setSelectedModel("openai:accounts/fireworks/models/qwen3p6-plus");
      const workspaceResponse = await getWorkspaces();
      const nextWorkspaces = workspaceResponse.workspaces.length
        ? workspaceResponse.workspaces
        : [await createWorkspace("default")];
      setWorkspaces(nextWorkspaces);
      await openWorkspace(nextWorkspaces[0].name, nextConfig);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to initialize workspace");
    }
  }

  async function refreshWorkspaces() {
    const response = await getWorkspaces();
    setWorkspaces(response.workspaces);
  }

  async function openWorkspace(name: string, activeConfig = config) {
    if (!activeConfig) return;
    setActiveWorkspace(name);
    setSelectedPath("");
    setFileContent("");
    setSavedContent("");
    setThinkingItems([]);
    setLastSubmittedPrompt("");
    setFinalOutput("");
    setStreamingAssistantText("");
    streamBufferRef.current = "";
    structuredEventsSeenRef.current = false;
    backendFailureRef.current = false;
    lastDerivedThinkingKeyRef.current = "";
    const firstThreadId = crypto.randomUUID();
    setTerminalLines((current) => [...current, `$ workspace ${name}`]);
    const modelForSession = selectedModel || activeConfig.defaultModel;
    const created = await createSession({
      workspace: name,
      workspaceMode: "local",
      mode: "accept_edits",
      model: modelForSession,
    });
    setChatThreads([{ id: firstThreadId, title: "Agents", runs: [], backendSession: created }]);
    setActiveThreadId(firstThreadId);
    setSession(created);
    await refreshWorkspace(created.id);
    setError(null);
  }

  async function addWorkspace() {
    const name = window.prompt("Workspace name");
    if (!name?.trim()) return;
    try {
      const created = await createWorkspace(name);
      await refreshWorkspaces();
      await openWorkspace(created.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create workspace");
    }
  }

  async function refreshWorkspace(sessionId = session?.id) {
    if (!sessionId) return;
    const nextTree = await getFileTree(sessionId);
    setTree(nextTree);
  }

  async function selectFile(path: string) {
    if (!session) return;
    setSelectedPath(path);
    const content = await getFileContent(session.id, path);
    setFileContent(content.content);
    setSavedContent(content.content);
    setError(null);
  }

  async function saveFile() {
    if (!session || !selectedPath) return;
    setIsSaving(true);
    try {
      const updated = await applyFile(session.id, selectedPath, fileContent);
      setFileContent(updated.content);
      setSavedContent(updated.content);
      await refreshWorkspace();
      setError(null);
      setTerminalLines((current) => [...current, `[saved] ${selectedPath}`]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to save file";
      setError(message);
      setTerminalLines((current) => [...current, `[error] ${message}`]);
    } finally {
      setIsSaving(false);
    }
  }

  async function runAgent() {
    if (!config || isRunning || runInFlightRef.current) return;
    const userPrompt = prompt.trim();
    if (!userPrompt) return;
    runInFlightRef.current = true;
    let threadIdAtSend = activeThreadId || chatThreads[0]?.id || "";
    if (!threadIdAtSend) {
      threadIdAtSend = crypto.randomUUID();
      setChatThreads([{ id: threadIdAtSend, title: "Chat", runs: [] }]);
      setActiveThreadId(threadIdAtSend);
    }
    setPrompt("");
    setIsRunning(true);
    setLastSubmittedPrompt(userPrompt);
    const provisionalTitle = deriveAgentTitle(userPrompt);
    setAgentTitle(provisionalTitle);
    setRecentPrompts((current) => [userPrompt, ...current.filter((p) => p !== userPrompt)].slice(0, 8));
    setError(null);
    setFinalOutput("");
    setThinkingItems([]);
    setStreamingAssistantText("");
    streamBufferRef.current = "";
    structuredEventsSeenRef.current = false;
    backendFailureRef.current = false;
    lastDerivedThinkingKeyRef.current = "";
    setTerminalLines((current) => [...current, "", `$ agent ${userPrompt.slice(0, 90)}`]);
    let latestReasoningText = "";
    let sawAssistantToken = false;
    let sawAnyEvent = false;
    let runFinalOutput = "";
    let latestErrorText = "";
    let liveThinkingItems: ThinkingItem[] = [];
    const activeModel = selectedModel || config.defaultModel;
    const executeRun = async (sessionId: string, priorRuns: CompletedRun[]) => {
      setChatThreads((current) =>
        current.map((thread) =>
          thread.id === threadIdAtSend && thread.runs.length === 0
            ? { ...thread, title: provisionalTitle }
            : thread,
        ),
      );
      const transcriptMessages = priorRuns.flatMap((r) => [
        { role: "user" as const, content: r.prompt },
        { role: "assistant" as const, content: r.finalOutput },
      ]);
      await streamRun(
        sessionId,
        {
          message: userPrompt,
          messages: [...transcriptMessages, { role: "user", content: userPrompt }],
          model: activeModel,
          mode: "accept_edits",
        },
        (event) => {
        sawAnyEvent = true;
        const terminalLine = terminalLineForEvent(event);
        if (terminalLine) {
          setTerminalLines((current) => [...current, terminalLine]);
        }
        const thinkingText = thinkingLineForEvent(event);
        if (thinkingText) {
          const kind = thinkingKindForEvent(event);
          if (kind === "thinking") latestReasoningText = thinkingText;
          const last = liveThinkingItems[liveThinkingItems.length - 1];
          if (kind === "thinking" && last && last.kind === "thinking") {
            const joiner = last.text.endsWith(" ") || thinkingText.startsWith(" ") ? "" : " ";
            liveThinkingItems = [
              ...liveThinkingItems.slice(0, -1),
              { ...last, text: `${last.text}${joiner}${thinkingText}`.trim() },
            ];
          } else if (!(last && last.kind === kind && last.text === thinkingText)) {
            liveThinkingItems = [...liveThinkingItems, { id: crypto.randomUUID(), kind, text: thinkingText }];
          }
          setThinkingItems(liveThinkingItems);
        }
        if (
          event.type === "thinking" ||
          event.type === "tool_call" ||
          event.type === "approval_required" ||
          event.type === "file_change" ||
          event.type === "todo" ||
          event.type === "custom" ||
          event.type === "update"
        ) {
          structuredEventsSeenRef.current = true;
        }
        if (event.type === "error") {
          structuredEventsSeenRef.current = true;
          backendFailureRef.current = true;
          const errText = (event.message || "Agent run failed").trim();
          latestErrorText = errText;
          // Keep error in the chat timeline only (thinking/tool cards); avoid duplicating in bottom banner.
        }
        if (event.type === "token" && event.message) {
          sawAssistantToken = true;
          streamBufferRef.current += event.message;
          setStreamingAssistantText(streamBufferRef.current);
        }
        if (event.type === "approval_required") {
          setApproval(event.data as unknown as ApprovalData);
        }
        if (event.type === "done") {
          if (streamBufferRef.current.trim()) {
            setFinalOutput(streamBufferRef.current.trim());
            runFinalOutput = streamBufferRef.current.trim();
            streamBufferRef.current = "";
            setStreamingAssistantText("");
          } else if (!sawAssistantToken && latestReasoningText.trim()) {
            setFinalOutput(latestReasoningText.trim());
            runFinalOutput = latestReasoningText.trim();
          } else if (!runFinalOutput) {
            runFinalOutput = "Run completed without assistant text.";
            setFinalOutput(runFinalOutput);
          }
        }
      });
      await refreshWorkspace(sessionId);
    };

    try {
      const threadSnapshot = chatThreads.find((t) => t.id === threadIdAtSend);
      let sessionForRun = threadSnapshot?.backendSession ?? null;

      if (!sessionForRun) {
        sessionForRun = await createSession({
          workspace: activeWorkspace,
          workspaceMode: "local",
          mode: "accept_edits",
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
      setTerminalLines((current) => [...current, `[error] ${message}`]);
      const errorItem: ThinkingItem = { id: crypto.randomUUID(), kind: "error", text: message };
      liveThinkingItems = [...liveThinkingItems, errorItem];
      setThinkingItems((current) => [...current, errorItem]);
      structuredEventsSeenRef.current = true;
      backendFailureRef.current = true;
      latestErrorText = message;
      runFinalOutput = "";
    } finally {
      runInFlightRef.current = false;
      if (streamBufferRef.current.trim()) {
        const full = streamBufferRef.current.trim();
        setFinalOutput(full);
        runFinalOutput = full;
        if (!structuredEventsSeenRef.current && !backendFailureRef.current) {
          const derived = extractThinkingAndToolsFromAssistantText(full);
          lastDerivedThinkingKeyRef.current = derived.map((d) => `${d.kind}:${d.text}`).join("\n");
          setThinkingItems(derived);
          liveThinkingItems = derived;
        }
        streamBufferRef.current = "";
        setStreamingAssistantText("");
      }
      if (!runFinalOutput && !liveThinkingItems.length) {
        const fallback = sawAnyEvent
          ? "Run completed, but no assistant response text was returned."
          : "No stream events received from backend.";
        runFinalOutput = fallback;
        setFinalOutput(fallback);
      }
      const safeFinalOutput = (runFinalOutput || latestReasoningText || "").trim();
      const dedupedFinalOutput = latestErrorText && safeFinalOutput === latestErrorText ? "" : safeFinalOutput;
      if (userPrompt) {
        const completed: CompletedRun = {
          id: crypto.randomUUID(),
          prompt: userPrompt,
          thinkingItems: liveThinkingItems,
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
      setThinkingItems([]);
      setFinalOutput("");
      setStreamingAssistantText("");
      setIsRunning(false);
    }
  }

  useEffect(() => {
    // If the backend emitted structured thinking/tool events, we render those directly.
    if (structuredEventsSeenRef.current) return;
    if (backendFailureRef.current) return;
    const text = streamingAssistantText || finalOutput;
    if (!text) return;

    const derived = extractThinkingAndToolsFromAssistantText(text);
    const key = derived.map((d) => `${d.kind}:${d.text}`).join("\n");
    if (!key) return;
    if (key === lastDerivedThinkingKeyRef.current) return;
    lastDerivedThinkingKeyRef.current = key;
    setThinkingItems(derived);
  }, [streamingAssistantText, finalOutput]);

  async function handleApproval(decision: "approve" | "reject") {
    if (!approval) return;
    await decideInterrupt(approval.runId, approval.interruptId, decision);
    setTerminalLines((current) => [...current, `[${decision}] ${approval.tool}`]);
    setApproval(null);
  }

  const hasUnsavedChanges = !!selectedPath && fileContent !== savedContent;
  const saveLabel = !selectedPath ? "Open a file to save" : isSaving ? "Saving..." : hasUnsavedChanges ? "Save" : "Saved";
  const hasPromptText = prompt.trim().length > 0;

  function newTask() {
    const nextIndex = chatThreads.length + 1;
    const id = crypto.randomUUID();
    setChatThreads((current) => [{ id, title: `Chat ${nextIndex}`, runs: [], backendSession: undefined }, ...current]);
    setActiveThreadId(id);
    setAgentTitle(`Chat ${nextIndex}`);
    setPrompt("");
    setShowHistory(false);
    setShowActions(false);
  }

  function clearRunOutput() {
    setFinalOutput("");
    setStreamingAssistantText("");
    setThinkingItems([]);
    setShowActions(false);
  }

  function resetAgentTitle() {
    setAgentTitle("Agents");
    setShowActions(false);
  }

  return (
    <main className="ide-shell">
      <aside className="activity-bar">
        <div className="activity-logo">
          <Code2 />
        </div>
      </aside>

      <aside className="explorer-pane">
        <div className="brand-strip">
          <div>
            <h1>Agents</h1>
            <p>{config?.defaultModel ?? "Loading model"}</p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => void boot()} title="Refresh">
            <RefreshCw />
          </Button>
        </div>

        <section className="workspace-switcher">
          <div className="pane-title">
            <span>Workspaces</span>
            <Button variant="ghost" size="icon" onClick={() => void addWorkspace()} title="New workspace">
              <Plus />
            </Button>
          </div>
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
        </section>

        <section className="file-pane">
          <div className="pane-title">
            <span>Files</span>
            <Button variant="ghost" size="icon" onClick={() => void refreshWorkspace()} title="Refresh files">
              <RefreshCw />
            </Button>
          </div>
          <FileTree node={tree} selectedPath={selectedPath} onSelect={(path) => void selectFile(path)} />
        </section>
      </aside>

      <section className="workbench-pane">
        <header className="editor-tabbar">
          <button className="tab active" type="button">
            <FilePlus2 />
            {selectedPath || "untitled"}
          </button>
          <div className="editor-actions">
            <span>{session?.cwd ?? "No workspace"}</span>
            <Button
              disabled={!selectedPath || !hasUnsavedChanges || isSaving}
              variant="ghost"
              size="sm"
              onClick={() => void saveFile()}
              title={saveLabel}
            >
              <Save data-icon="inline-start" />
              {saveLabel}
            </Button>
          </div>
        </header>

        <section className="editor-area">
          <Editor
            height="100%"
            language={editorLanguage}
            theme="vs-dark"
            value={fileContent}
            onChange={(value) => setFileContent(value ?? "")}
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
        </section>

        <section className="terminal-dock">
          <div className="terminal-header">
            <div>
              <SquareTerminal />
              <span>Terminal</span>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setTerminalLines(["Agents terminal ready."])}>
              Clear
            </Button>
          </div>
          <pre className="terminal-output" ref={terminalOutputRef} tabIndex={-1}>
            {terminalLines.join("\n")}
          </pre>
        </section>
      </section>

      <aside className="agent-chat-pane">
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
              {!activeThread?.runs.length && !lastSubmittedPrompt && thinkingItems.length === 0 && !streamingAssistantText && !finalOutput ? (
                <div className="agent-empty-state">
                  <h3>How can I help you today?</h3>
                  <p>Ask anything or describe the edit you want to make.</p>
                </div>
              ) : (
                <>
                  {(activeThread?.runs ?? []).map((run) => (
                    <div key={run.id} className="timeline-run-group">
                      <article className="timeline-card user">{renderTextWithCodeFences(run.prompt)}</article>
                      {run.thinkingItems.map((entry) => (
                        <article className={`timeline-card ${entry.kind}`} key={entry.id}>
                          {entry.kind === "thinking" ? (
                            renderTextWithCodeFences(entry.text, "preserveLines")
                          ) : entry.kind === "tool" || entry.kind === "error" ? (
                            <pre>{entry.text}</pre>
                          ) : (
                            <p>{entry.text}</p>
                          )}
                        </article>
                      ))}
                      {run.finalOutput && <article className="timeline-card assistant">{renderTextWithCodeFences(run.finalOutput)}</article>}
                    </div>
                  ))}

                  {lastSubmittedPrompt && (
                    <div className="timeline-run-group current-live-run">
                      <article className="timeline-card user">
                        {renderTextWithCodeFences(lastSubmittedPrompt)}
                      </article>
                      {thinkingItems.map((entry) => (
                        <article className={`timeline-card ${entry.kind}`} key={entry.id}>
                          {entry.kind === "thinking" ? (
                            renderTextWithCodeFences(entry.text, "preserveLines")
                          ) : entry.kind === "tool" || entry.kind === "error" ? (
                            <pre>{entry.text}</pre>
                          ) : (
                            <p>{entry.text}</p>
                          )}
                        </article>
                      ))}
                      {isRunning && thinkingItems.length === 0 && !streamingAssistantText && !finalOutput && (
                        <article className="timeline-card thinking">
                          <p>Thinking...</p>
                        </article>
                      )}
                      {streamingAssistantText && (
                        <article className="timeline-card assistant live">
                          {renderTextWithCodeFences(streamingAssistantText)}
                        </article>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>

            <section className="agent-composer">
              <Textarea
                ref={composerTextareaRef}
                className="agent-textarea !min-h-[52px] border-0 bg-transparent px-0 py-0 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
                value={prompt}
                onChange={(event) => {
                  setPrompt(event.target.value);
                  queueMicrotask(resizeComposerTextarea);
                }}
                placeholder="Ask anything, @ to mention, / for workflows..."
                rows={1}
              />
              <div className="agent-composer-footer">
                <div className="agent-composer-tools">
                  <button className="composer-icon-button" type="button" title="Add context">
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
                        {FIREWORKS_MODEL_OPTIONS.map((model) => (
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
                </div>
                <button
                  className="composer-primary-button"
                  type="button"
                  disabled={isRunning}
                  onClick={() => void runAgent()}
                  title={isRunning ? "Running..." : hasPromptText ? "Send" : "Voice"}
                >
                  {hasPromptText ? <ArrowUp /> : <Mic />}
                </button>
              </div>
            </section>

            <p className="agent-footnote">AI may make mistakes. Double-check all generated code.</p>
          </div>
        </div>

        {error && (
          <div className="error-callout">
            <X />
            <span>{error}</span>
          </div>
        )}
      </aside>

      {approval && (
        <div className="approval-backdrop">
          <div className="approval-dialog">
            <div>
              <h2>Approve terminal command</h2>
              <p>{approval.tool}</p>
            </div>
            <pre>{JSON.stringify(approval.payload, null, 2)}</pre>
            <div className="approval-actions">
              <Button variant="outline" onClick={() => void handleApproval("reject")}>
                Reject
              </Button>
              <Button onClick={() => void handleApproval("approve")}>
                <Check data-icon="inline-start" />
                Approve
              </Button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

function terminalLineForEvent(event: StreamEvent): string | null {
  if (event.type === "custom" || event.type === "update") return null;
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
    const payload = event.data.payload;
    const command =
      typeof payload === "object" && payload && "command" in payload ? String((payload as { command: unknown }).command) : formatData(payload);
    return `[approval required] ${tool}: ${command}`;
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

function thinkingKindForEvent(event: StreamEvent): "tool" | "thinking" | "error" {
  if (event.type === "error") return "error";
  if (event.type === "tool_call") return "tool";
  return "thinking";
}

function thinkingLineForEvent(event: StreamEvent): string | null {
  if (event.type === "custom" || event.type === "update") return null;
  if (event.type === "thinking") {
    const text = (event.message || "").replace(/\s+/g, " ").trim();
    if (!text) return null;
    if (/^graph update$/i.test(text)) return null;
    return text;
  }
  if (event.type === "tool_call") {
    const tool = readString(event.data.name) || "tool";
    const command =
      typeof event.data.args === "object" && event.data.args && "command" in event.data.args
        ? String((event.data.args as { command: unknown }).command)
        : "";
    if (command) return `$ ${command}`;
    const output = readString(event.data.result).trim();
    if (output && output.length < 80) return output;
    return `Called ${tool}`;
  }
  if (event.type === "approval_required") {
    const tool = readString(event.data.tool) || "tool";
    return `Approval required: ${tool}`;
  }
  if (event.type === "file_change") {
    return event.message || formatData(event.data) || "File changed";
  }
  if (event.type === "error") {
    return event.message || formatData(event.data) || "Agent error";
  }
  if (event.type === "done") return null;
  return null;
}

/** Matches ``` fences with optional lang; allows newline after opener to be optional (provider quirks). */
const CODE_FENCE_RE = /```(?:[a-zA-Z0-9_-]*)?\s*\n?([\s\S]*?)```/g;

type RichTextMode = "reflow" | "preserveLines";

function renderTextWithCodeFences(text: string, mode: RichTextMode = "reflow") {
  const nodes: ReactElement[] = [];
  let lastIndex = 0;
  let idx = 0;

  for (const match of text.matchAll(CODE_FENCE_RE)) {
    const full = match[0];
    const code = match[1] ?? "";
    const start = match.index ?? 0;

    if (start > lastIndex) {
      const slice = text.slice(lastIndex, start);
      nodes.push(
        <span key={`t-${idx++}`}>
          {mode === "reflow"
            ? renderMarkdownishText(slice, `m-${idx}`)
            : renderMarkdownishPreserveLines(slice, `m-${idx}`)}
        </span>,
      );
    }

    nodes.push(
      <pre key={`c-${idx++}`}>
        {code.trimEnd()}
      </pre>,
    );

    lastIndex = start + full.length;
  }

  if (lastIndex < text.length) {
    const tail = text.slice(lastIndex);
    nodes.push(
      <span key={`t-${idx++}`}>
        {mode === "reflow" ? renderMarkdownishText(tail, `m-${idx}`) : renderMarkdownishPreserveLines(tail, `m-${idx}`)}
      </span>,
    );
  }

  return <div className="timeline-rich-text">{nodes}</div>;
}

function renderMarkdownishText(raw: string, keyPrefix: string): ReactElement {
  const lines = normalizeAndReflowText(raw);

  return (
    <div className="rich-markdownish">
      {lines.map((line, i) => (
        <p key={`${keyPrefix}-${i}`}>{renderInlineBold(line, `${keyPrefix}-b-${i}`)}</p>
      ))}
    </div>
  );
}

/** Reasoning streams: keep model line breaks; do not merge into one paragraph. */
function renderMarkdownishPreserveLines(raw: string, keyPrefix: string): ReactElement {
  const normalized = raw.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");

  return (
    <div className="rich-markdownish rich-markdownish-preserve">
      {lines.map((line, i) => (
        <p key={`${keyPrefix}-ln-${i}`}>
          {line.length ? renderInlineBold(line, `${keyPrefix}-b-${i}`) : "\u00a0"}
        </p>
      ))}
    </div>
  );
}

function renderInlineBold(line: string, keyPrefix: string): Array<string | ReactElement> {
  const parts: Array<string | ReactElement> = [];
  const re = /\*\*(.+?)\*\*/g;
  let last = 0;
  let idx = 0;
  for (const match of line.matchAll(re)) {
    const start = match.index ?? 0;
    if (start > last) parts.push(line.slice(last, start));
    parts.push(<strong key={`${keyPrefix}-${idx++}`}>{match[1]}</strong>);
    last = start + match[0].length;
  }
  if (last < line.length) parts.push(line.slice(last));
  return parts.length ? parts : [line];
}

function extractThinkingAndToolsFromAssistantText(text: string): Array<{ id: string; kind: "tool" | "thinking" | "error"; text: string }> {
  // Heuristic fallback: Deep Agents sometimes streams “tool usage” as plain markdown text
  // (code fences with shell commands), not as structured `tool_call`/`thinking` SSE events.
  const items: Array<{ id: string; kind: "tool" | "thinking" | "error"; text: string }> = [];

  const thinkRe = /<think[^>]*>([\s\S]*?)<\/think>/gi;
  let thinkMatch: RegExpExecArray | null;
  const thinkParts: string[] = [];
  while ((thinkMatch = thinkRe.exec(text)) !== null) {
    const part = (thinkMatch[1] || "").trim();
    if (part) thinkParts.push(part);
  }
  if (thinkParts.length) {
    const first = thinkParts[0].split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 3).join("\n");
    if (first) items.push({ id: crypto.randomUUID(), kind: "thinking", text: first });
  }

  // Steps like: "1. List workspace files:" -> thinking card.
  const stepRe = /^\s*(\d+)\.\s*([^:\n]+):/gm;
  const steps: string[] = [];
  for (const match of text.matchAll(stepRe)) {
    const num = match[1];
    const desc = (match[2] || "").trim();
    if (!desc) continue;
    steps.push(`Step ${num}: ${desc}`);
    if (steps.length >= 5) break;
  }
  for (const step of steps) {
    items.push({ id: crypto.randomUUID(), kind: "thinking", text: step });
  }

  // Code fences with shell-like commands -> tool call cards.
  const fenceRe = /```[a-zA-Z0-9_-]*\n([\s\S]*?)```/g;
  const cmdLineRe =
    /^\s*(?:\$|>)?\s*(ls|pwd|cd|cat|sed|awk|grep|find|rm|cp|mv|mkdir|chmod|chown|git|npm|pnpm|yarn|python|pytest|make|curl|wget|docker|docker-compose|kubectl)\b/;

  for (const match of text.matchAll(fenceRe)) {
    const rawCode = (match[1] || "").trimEnd();
    if (!rawCode) continue;
    const lines = rawCode.split("\n");
    const commandish = lines.some((l) => cmdLineRe.test(l));
    if (!commandish) continue;
    items.push({ id: crypto.randomUUID(), kind: "tool", text: rawCode });
  }

  // If we didn't detect anything, keep the UI clean.
  return items.slice(0, 12);
}

function formatModelLabel(model: string | undefined): string {
  if (!model) return "Loading model";
  const normalized = model.toLowerCase();
  if (normalized.includes("minimax-m2")) return "model minimax m2";
  if (normalized.includes("qwen3p6-plus")) return "model qwen3.6 plus";
  if (normalized.includes("kimi-k2-thinking")) return "model kimi k2 thinking";
  if (normalized.includes("glm-4p7")) return "model glm 4.7";
  const slashPart = model.split("/").pop() || model;
  return `model ${slashPart.replace(/^models[:/-]?/i, "")}`;
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

function normalizeAndReflowText(raw: string): string[] {
  const normalized = raw
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/ +([.,!?;:])/g, "$1")
    .replace(/([(\[{]) +/g, "$1")
    .replace(/ +([)\]}])/g, "$1")
    .replace(/ +'\s*/g, "'")
    .trim();

  const srcLines = normalized.split("\n").map((line) => line.trim()).filter(Boolean);
  const out: string[] = [];
  let current = "";

  const flush = () => {
    if (current.trim()) out.push(current.trim());
    current = "";
  };

  for (const line of srcLines) {
    const structural = /^[-*•]\s+/.test(line) || /^\d+[.)]\s+/.test(line) || /^#{1,6}\s+/.test(line);
    if (structural) {
      flush();
      out.push(line);
      continue;
    }
    current = current ? `${current} ${line}` : line;
  }
  flush();
  return out;
}
