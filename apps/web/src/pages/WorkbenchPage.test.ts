import { describe, expect, it } from "vitest";

import type { ApprovalData } from "../types/api";
import { formatModeLabel, readApprovalCommand } from "./WorkbenchPage";

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
    expect(formatModeLabel("ask_before_edits")).toBe("mode ask before edits");
    expect(formatModeLabel("accept_edits")).toBe("mode accept edits");
    expect(formatModeLabel("accept_everything")).toBe("mode accept everything");
  });
});
