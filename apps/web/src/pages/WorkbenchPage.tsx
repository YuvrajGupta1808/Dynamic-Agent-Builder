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
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import ReactMarkdown from "react-markdown";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";
import { Link } from "react-router-dom";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import { EventTimeline } from "../components/EventTimeline";
import { FileTree } from "../components/FileTree";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
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
    transcribeAudio,
} from "../lib/api";
import { setRequireClerkJwt } from "../lib/auth-token";
import { cn } from "../lib/utils";
import type {
    AppConfig,
    ApprovalData,
    ChatContentPart,
    FileTreeNode,
    SessionMode,
    SessionRecord,
    StreamEvent,
    TodoItem,
    WorkspaceSummary,
} from "../types/api";

export function WorkbenchPage() {
  const FIREWORKS_MODEL_OPTIONS = [
    "openai:accounts/fireworks/models/glm-4p7",
    "openai:accounts/fireworks/models/qwen3p6-plus",
  ] as const;
  type ThinkingItem = {
    id: string;
    kind: "tool" | "thinking" | "error";
    text: string;
  };
  type CompletedRun = {
    id: string;
    prompt: string;
    promptImages: string[];
    thinkingItems: ThinkingItem[];
    events: StreamEvent[];
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

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWorkspace, setActiveWorkspace] = useState<string>("");
  const [workspaceModalOpen, setWorkspaceModalOpen] = useState(false);
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [session, setSession] = useState<SessionRecord | null>(null);
  const [tree, setTree] = useState<FileTreeNode | null>(null);
  const [selectedPath, setSelectedPath] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [terminalLines, setTerminalLines] = useState<string[]>(["Agents terminal ready."]);
  const [prompt, setPrompt] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalData[]>([]);
  const [approvalFeedback, setApprovalFeedback] = useState("");
  const [approvalEditDraft, setApprovalEditDraft] = useState("");
  const [approvalEditMode, setApprovalEditMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [thinkingItems, setThinkingItems] = useState<ThinkingItem[]>([]);
  const [lastSubmittedPrompt, setLastSubmittedPrompt] = useState("");
  const [finalOutput, setFinalOutput] = useState("");
  const [streamingAssistantText, setStreamingAssistantText] = useState("");
  const [liveRunEvents, setLiveRunEvents] = useState<StreamEvent[]>([]);
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
  const streamBufferRef = useRef("");
  const structuredEventsSeenRef = useRef(false);
  const backendFailureRef = useRef(false);
  const lastDerivedThinkingKeyRef = useRef("");
  const runInFlightRef = useRef(false);
  const didBootRef = useRef(false);
  const chatPaneRef = useRef<HTMLDivElement>(null);
  const terminalOutputRef = useRef<HTMLPreElement>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaChunksRef = useRef<BlobPart[]>([]);
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
        setTree(null);
        setSelectedPath("");
        setFileContent("");
        setSavedContent("");
        setChatThreads([{ id: tid, title: "Agents", runs: [] }]);
        setActiveThreadId(tid);
        setTerminalLines([
          "Welcome to Dynamic Agent Studio.",
          "Create a workspace (center panel) to open the editor, file tree, and agent.",
        ]);
      }
      setError(null);
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
    setLiveRunEvents([]);
    setPendingApprovals([]);
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
      mode: selectedMode,
      model: modelForSession,
    });
    setChatThreads([{ id: firstThreadId, title: "Agents", runs: [], backendSession: created }]);
    setActiveThreadId(firstThreadId);
    setSession(created);
    await refreshWorkspace(created.id);
    await openWorkspaceReadme(created.id);
    setError(null);
  }

  async function openWorkspaceReadme(sessionId: string) {
    try {
      const readme = await getFileContent(sessionId, "README.md");
      setSelectedPath("README.md");
      setFileContent(readme.content);
      setSavedContent(readme.content);
    } catch {
      // Some pre-existing workspaces may not have a README; keep editor empty in that case.
    }
  }

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

  function openWorkspaceModal() {
    setNewWorkspaceName(generateRandomWorkspaceName());
    setWorkspaceModalOpen(true);
  }

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
    setFinalOutput("");
    setThinkingItems([]);
    setStreamingAssistantText("");
    setLiveRunEvents([]);
    setPendingApprovals([]);
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
    let liveEvents: StreamEvent[] = [];
    const seenThinkingTexts = new Set<string>();
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
      await streamRun(
        sessionId,
        {
          message: userPrompt,
          messages: [...transcriptMessages, { role: "user", content: currentUserContent }],
          model: activeModel,
          mode: selectedMode,
        },
        (event) => {
        liveEvents = [...liveEvents, event];
        setLiveRunEvents(liveEvents);
        sawAnyEvent = true;
        const terminalLine = terminalLineForEvent(event);
        if (terminalLine) {
          setTerminalLines((current) => [...current, terminalLine]);
        }
        const thinkingText = thinkingLineForEvent(event);
        if (thinkingText) {
          const kind = thinkingKindForEvent(event);
          if (kind === "thinking") {
            const normalizedThinking = thinkingText.trim();
            if (seenThinkingTexts.has(normalizedThinking)) {
              return;
            }
            seenThinkingTexts.add(normalizedThinking);
            latestReasoningText = normalizedThinking;
          }
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
          const nextApproval = event.data as unknown as ApprovalData;
          setPendingApprovals((current) => {
            if (current.some((item) => item.interruptId === nextApproval.interruptId)) {
              return current;
            }
            return [...current, nextApproval];
          });
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
          promptImages: activeImageAttachments.map((item) => item.dataUrl),
          thinkingItems: liveThinkingItems,
          events: liveEvents,
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
      setLiveRunEvents([]);
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

  async function handleApproval(
    decision: "approve" | "reject" | "edit",
    options: { reason?: string; editedAction?: Record<string, unknown> } = {},
  ) {
    if (!approval) return;
    setIsDecidingApproval(true);
    try {
      await decideInterrupt(approval.runId, approval.interruptId, {
        decision,
        reason: options.reason,
        editedAction: options.editedAction,
      });
      const approvalLabel = approvalCheckpointLabel(approval);
      setTerminalLines((current) => [...current, `[${decision}] ${approval.tool}${approvalLabel ? ` (${approvalLabel})` : ""}`]);
      setPendingApprovals((current) => current.filter((item) => item.interruptId !== approval.interruptId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit approval decision.");
    } finally {
      setIsDecidingApproval(false);
    }
  }

  async function approveCurrentApproval() {
    await handleApproval("approve");
  }

  async function rejectCurrentApproval() {
    const reason = approvalFeedback.trim() || defaultRejectReason(approval);
    await handleApproval("reject", { reason });
  }

  async function submitEditedApproval() {
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
  }

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
    setFinalOutput("");
    setStreamingAssistantText("");
    setThinkingItems([]);
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

  function toggleTerminal() {
    if (!terminalPanelRef.current) return;
    if (terminalPanelRef.current.isCollapsed()) {
      terminalPanelRef.current.expand();
      return;
    }
    terminalPanelRef.current.collapse();
  }

  function closeEditorTab() {
    if (!selectedPath) return;
    if (hasUnsavedChanges) {
      const ok = window.confirm("Discard unsaved changes for this file?");
      if (!ok) return;
    }
    setSelectedPath("");
    setFileContent("");
    setSavedContent("");
  }

  const workspaceMissing = workspaces.length === 0 || !session;

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
                  <p>{config?.defaultModel ?? "Loading model"}</p>
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
                {workspaceMissing ? (
                  <div className="file-pane-idle">
                    <p>Files from your workspace will list here.</p>
                  </div>
                ) : (
                  <FileTree node={tree} selectedPath={selectedPath} onSelect={(path) => void selectFile(path)} />
                )}
              </section>
            </aside>
          </Panel>

          <Separator className="resize-handle" />

          <Panel id="center" defaultSize="50%" minSize="36%" className="ide-panel-center">
            <section className="workbench-pane workbench-pane-fill">
              <header className="editor-tabbar">
                <div className="editor-tabs-row">
                  {selectedPath ? (
                    <div className="tab active editor-tab-with-close" role="presentation">
                      <FilePlus2 />
                      <span className="editor-tab-label">{selectedPath}</span>
                      <button
                        type="button"
                        className="editor-tab-close"
                        aria-label="Close file"
                        onClick={() => closeEditorTab()}
                      >
                        <X />
                      </button>
                    </div>
                  ) : (
                    <span className="editor-tab-placeholder">
                      {workspaceMissing ? "Workspace" : "No file open"}
                    </span>
                  )}
                </div>
                <div className="editor-actions">
                  <span className="editor-cwd-truncate">
                    {workspaceMissing ? "Set up a workspace to continue" : (session?.cwd ?? "—")}
                  </span>
                  <Button
                    disabled={!selectedPath || !hasUnsavedChanges || isSaving || workspaceMissing}
                    variant="ghost"
                    size="sm"
                    onClick={() => void saveFile()}
                    title={saveLabel}
                  >
                    <Save data-icon="inline-start" />
                    {saveLabel}
                  </Button>
                  <Button variant="ghost" size="icon" type="button" title="Toggle terminal" onClick={toggleTerminal}>
                    <SquareTerminal />
                  </Button>
                </div>
              </header>

              <Group orientation="vertical" className="workbench-center-group" resizeTargetMinimumSize={{ coarse: 18, fine: 10 }}>
                <Panel id="editorPanel" defaultSize="72%" minSize="38%" className="workbench-center-editor-panel">
                  <section className={`editor-area ${workspaceMissing ? "editor-area-idle" : ""}`}>
                    {workspaceMissing ? (
                      <div className="workbench-empty-canvas">
                        <p className="workbench-empty-kicker">Getting started</p>
                        <h2 className="workbench-empty-heading">Create a workspace</h2>
                        <p className="workbench-empty-lead">
                          You’ll get an isolated folder with a README, a file tree, and a safe place for the agent to work—nothing
                          outside it unless you configure that.
                        </p>
                        <Button type="button" size="default" className="workbench-empty-cta" onClick={openWorkspaceModal}>
                          Get started
                        </Button>
                      </div>
                    ) : (
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
                  <section className={`terminal-dock ${workspaceMissing ? "terminal-dock-idle" : ""}`}>
                    <div className="terminal-header">
                      <div>
                        <SquareTerminal />
                        <span>Terminal</span>
                      </div>
                      <div className="terminal-actions">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            setTerminalLines(
                              workspaceMissing
                                ? [
                                    "Welcome to Dynamic Agent Studio.",
                                    "Create a workspace (center panel) to open the editor, file tree, and agent.",
                                  ]
                                : ["Agents terminal ready."],
                            )
                          }
                        >
                          Clear
                        </Button>
                        <Button variant="ghost" size="icon" type="button" title="Close terminal" onClick={toggleTerminal}>
                          <X />
                        </Button>
                      </div>
                    </div>
                    <pre className="terminal-output" ref={terminalOutputRef} tabIndex={-1}>
                      {terminalLines.join("\n")}
                    </pre>
                  </section>
                </Panel>
              </Group>
            </section>
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
              {!activeThread?.runs.length && !lastSubmittedPrompt && thinkingItems.length === 0 && !streamingAssistantText && !finalOutput ? (
                <div className="agent-empty-state">
                  <h3>How can I help you today?</h3>
                  <p>Ask anything or describe the edit you want to make.</p>
                </div>
              ) : (
                <>
                  {(activeThread?.runs ?? []).map((run) => (
                    <div key={run.id} className="timeline-run-group">
                      <article className="timeline-card user">
                        {renderTextWithCodeFences(run.prompt)}
                        {run.promptImages.length > 0 && (
                          <div className="timeline-inline-images">
                            {run.promptImages.map((url) => (
                              <img key={url} src={url} alt="User upload" className="timeline-inline-image" />
                            ))}
                          </div>
                        )}
                      </article>
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
                      <RunOrchestrationTrace events={run.events} />
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
                      <RunOrchestrationTrace events={liveRunEvents} live={isRunning} />
                      {isRunning && thinkingItems.length === 0 && !streamingAssistantText && !finalOutput && (
                        <article className="timeline-card thinking">
                          <p>Thinking...</p>
                        </article>
                      )}
                      {approval && (
                        <ApprovalReviewCard
                          approval={approval}
                          pendingCount={pendingApprovals.length}
                          feedback={approvalFeedback}
                          editDraft={approvalEditDraft}
                          editMode={approvalEditMode}
                          busy={isDecidingApproval}
                          onFeedbackChange={setApprovalFeedback}
                          onEditDraftChange={setApprovalEditDraft}
                          onToggleEditMode={setApprovalEditMode}
                          onReject={() => void rejectCurrentApproval()}
                          onApprove={() => void approveCurrentApproval()}
                          onSubmitEdit={() => void submitEditedApproval()}
                        />
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

            <section className={cn("agent-composer", workspaceMissing && "agent-composer-idle")}>
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
                  workspaceMissing
                    ? "Create a workspace to start chatting with the agent…"
                    : "Ask anything, @ to mention, / for workflows..."
                }
                readOnly={workspaceMissing}
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
                  disabled={isRunning || workspaceMissing || isTranscribingAudio}
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

        {error && (
          <div className="error-callout">
            <X />
            <span>{error}</span>
          </div>
        )}
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

function thinkingKindForEvent(event: StreamEvent): "tool" | "thinking" | "error" {
  if (event.type === "error") return "error";
  if (event.type === "tool_call") return "tool";
  return "thinking";
}

function thinkingLineForEvent(event: StreamEvent): string | null {
  if (event.type === "custom" || event.type === "update") return null;
  if (event.type === "todo") {
    const items = readTodoItems(event.data.items);
    if (!items.length) return "Todo list updated";
    const active = items.find((item) => item.status === "active");
    return active ? `Working: ${active.text}` : `Todo: ${items.map((item) => item.text).join(", ")}`;
  }
  if (event.type === "subagent") {
    const name = readString(event.data.name) || prettifySpecialistLabel(event.source);
    const status = readString(event.data.status);
    const summary = event.message || readString(event.data.summary);
    return [name, status, summary].filter(Boolean).join(" · ");
  }
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
    return `Approval required: ${approvalSummaryFromData(tool, event.data.payload)}`;
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

type RichTextMode = "reflow" | "preserveLines";

function renderTextWithCodeFences(text: string, mode: RichTextMode = "reflow") {
  const source = mode === "preserveLines" ? preserveSingleLineBreaks(text) : text;
  return (
    <div className="timeline-rich-text markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
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
        {source}
      </ReactMarkdown>
    </div>
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

const SPECIALIST_NAMES = new Set([
  "decomposer",
  "template_selector",
  "agent_initializer",
  "workspace_initializer",
  "context_specialist",
  "cli_specialist",
  "sdk_specialist",
  "integration_specialist",
  "trigger_specialist",
  "session_specialist",
  "documentation_specialist",
  "editor",
  "tester",
  "validator",
  "publisher",
  "async_tester",
  "async_publisher",
  "async_session_specialist",
]);

function normalizeSpecialistSource(source: string): string | null {
  const cleaned = source.replace(/^tools:/, "").trim();
  return SPECIALIST_NAMES.has(cleaned) ? cleaned : null;
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
    return [readString(event.data.status), event.message || readString(event.data.summary)].filter(Boolean).join(" · ");
  }
  if (event.type === "tool_call") {
    const command =
      typeof event.data.args === "object" && event.data.args && "command" in event.data.args
        ? String((event.data.args as { command: unknown }).command ?? "")
        : "";
    const name = readString(event.data.name) || "tool";
    return command || name;
  }
  if (event.type === "file_change") return event.message || "File changed";
  if (event.type === "approval_required") return approvalSummaryForEvent(event);
  if (event.type === "todo") {
    const items = readTodoItems(event.data.items);
    return items.map((item) => `${item.status}: ${item.text}`).join(" | ");
  }
  return event.message || "";
}

function isVisibleTraceEvent(event: StreamEvent): boolean {
  return (
    event.type === "subagent" ||
    event.type === "tool_call" ||
    event.type === "file_change" ||
    event.type === "approval_required" ||
    event.type === "error"
  );
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

function collectSpecialistSummaries(events: StreamEvent[]) {
  const grouped = new Map<
    string,
    {
      status: string;
      latest: string;
      count: number;
    }
  >();
  for (const event of events) {
    const explicit = readString(event.data.name);
    const specialist = normalizeSpecialistSource(explicit) ?? normalizeSpecialistSource(event.source);
    if (!specialist) continue;
    const current = grouped.get(specialist) ?? { status: "", latest: "", count: 0 };
    const nextStatus =
      event.type === "subagent"
        ? readString(event.data.status) || current.status
        : current.status || (event.type === "error" ? "error" : "running");
    const latest = summarizeTraceEvent(event) || current.latest;
    grouped.set(specialist, { status: nextStatus, latest, count: current.count + 1 });
  }
  return [...grouped.entries()].map(([name, value]) => ({ name, ...value }));
}

function latestTodoSnapshot(events: StreamEvent[]): TodoItem[] {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "todo") {
      return readTodoItems(event.data.items);
    }
  }
  return [];
}

function RunOrchestrationTrace({ events, live = false }: { events: StreamEvent[]; live?: boolean }) {
  const traceEvents = events.filter(isVisibleTraceEvent);
  const specialistSummaries = collectSpecialistSummaries(traceEvents);
  const todoItems = latestTodoSnapshot(events);

  if (!traceEvents.length && !todoItems.length && !specialistSummaries.length) return null;

  return (
    <section className="timeline-trace-panel">
      <div className="timeline-trace-header">
        <span>{live ? "Agent activity" : "Run activity"}</span>
        <span>{traceEvents.length > 0 ? `${traceEvents.length} event${traceEvents.length === 1 ? "" : "s"}` : "summary"}</span>
      </div>
      {todoItems.length > 0 && (
        <div className="timeline-phase-list">
          {todoItems.map((item) => (
            <div key={item.id} className={`timeline-phase-chip ${item.status}`}>
              <span>{item.text}</span>
              <span>{item.status}</span>
            </div>
          ))}
        </div>
      )}
      {specialistSummaries.length > 0 && (
        <div className="timeline-specialist-grid">
          {specialistSummaries.map((item) => (
            <article key={item.name} className="timeline-specialist-card">
              <header>
                <span>{prettifySpecialistLabel(item.name)}</span>
                <span>{item.status || "active"}</span>
              </header>
              <p>{item.latest || "Working."}</p>
              <small>{item.count} event{item.count === 1 ? "" : "s"}</small>
            </article>
          ))}
        </div>
      )}
      {traceEvents.length > 0 ? (
        <details className="timeline-trace-details" open={false}>
          <summary>{live ? "Technical trace" : "Trace details"}</summary>
          <EventTimeline events={traceEvents} />
        </details>
      ) : null}
    </section>
  );
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

function preserveSingleLineBreaks(raw: string): string {
  return raw
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => (line.trim().length ? `${line}  ` : ""))
    .join("\n");
}
