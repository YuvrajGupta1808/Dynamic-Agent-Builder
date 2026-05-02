import { describe, expect, it } from "vitest";

import type { ApprovalData, StreamEvent } from "../types/api";
import {
  appendAssistantToken,
  appendRunBlock,
  extractRunBlocksFromAssistantText,
  formatModeLabel,
  mapEventToRunBlock,
  readApprovalCommand,
  type RunBlock,
} from "./WorkbenchPage";

describe("WorkbenchPage approval helpers", () => {
  it("extracts command from approval payload", () => {
    const approval: ApprovalData = {
      runId: "run-1",
      interruptId: "int-1",
      tool: "execute",
      payload: { command: "pwd" },
      status: "pending",
    };
    expect(readApprovalCommand(approval)).toBe("pwd");
  });

  it("returns empty command when payload has no command", () => {
    const approval: ApprovalData = {
      runId: "run-1",
      interruptId: "int-1",
      tool: "execute",
      payload: { cwd: "/workspace" },
      status: "pending",
    };
    expect(readApprovalCommand(approval)).toBe("");
  });
});

describe("WorkbenchPage mode labels", () => {
  it("formats mode labels for all session modes", () => {
    expect(formatModeLabel("ask_before_edits")).toBe("Ask before edits");
    expect(formatModeLabel("accept_edits")).toBe("Accept edits");
    expect(formatModeLabel("accept_everything")).toBe("Accept everything");
  });
});

describe("WorkbenchPage run blocks", () => {
  it("merges only adjacent blocks of the same kind", () => {
    const thinking: RunBlock = { id: "1", kind: "thinking", text: "Plan", eventType: "thinking" };
    const moreThinking: RunBlock = { id: "2", kind: "thinking", text: "Inspect files", eventType: "thinking" };
    const tool: RunBlock = { id: "3", kind: "tool", text: "$ rg foo", eventType: "tool_call" };

    const merged = appendRunBlock(appendRunBlock([thinking], moreThinking), tool);
    expect(merged).toHaveLength(2);
    expect(merged[0].kind).toBe("thinking");
    expect(merged[0].text).toBe("Plan Inspect files");
    expect(merged[1].kind).toBe("tool");
  });

  it("keeps assistant tokens inline after earlier orchestration blocks", () => {
    let blocks: RunBlock[] = [];
    const thinkingEvent: StreamEvent = {
      type: "thinking",
      runId: "run-1",
      sessionId: "session-1",
      sequence: 1,
      source: "main",
      message: "Scanning workspace",
      data: {},
    };
    const toolEvent: StreamEvent = {
      type: "tool_call",
      runId: "run-1",
      sessionId: "session-1",
      sequence: 2,
      source: "main",
      message: null,
      data: { name: "execute", args: { command: "pwd" } },
    };
    const thinkingBlock = mapEventToRunBlock(thinkingEvent);
    const toolBlock = mapEventToRunBlock(toolEvent);
    if (thinkingBlock) blocks = appendRunBlock(blocks, thinkingBlock);
    blocks = appendAssistantToken(blocks, "Draft ");
    if (toolBlock) blocks = appendRunBlock(blocks, toolBlock);
    blocks = appendAssistantToken(blocks, "answer");

    expect(blocks.map((block) => block.kind)).toEqual(["thinking", "assistant", "tool", "assistant"]);
    expect(blocks[1].text).toBe("Draft ");
    expect(blocks[3].text).toBe("answer");
  });

  it("preserves fallback order instead of moving all thinking first", () => {
    const blocks = extractRunBlocksFromAssistantText("Intro\n<think>Plan</think>\n```sh\npwd\n```\nFinal answer");
    expect(blocks.map((block) => block.kind)).toEqual(["assistant", "thinking", "tool", "assistant"]);
    expect(blocks[0].text).toContain("Intro");
    expect(blocks[3].text).toContain("Final answer");
  });
});
