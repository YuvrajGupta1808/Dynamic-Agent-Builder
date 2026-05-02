import { describe, expect, it } from "vitest";

import { renderTerminalAnsi } from "./terminal-ansi";

describe("renderTerminalAnsi", () => {
  it("renders ANSI color sequences as HTML spans", () => {
    const html = renderTerminalAnsi("\u001b[32mhello\u001b[0m");
    expect(html).toContain("hello");
    expect(html).toContain("<span");
  });

  it("normalizes carriage returns before rendering", () => {
    const html = renderTerminalAnsi("line1\rline2");
    expect(html).toContain("line2");
    expect(html).not.toContain("line1<br/>line2");
  });

  it("strips private-use icon glyphs that render as square boxes in the browser", () => {
    const html = renderTerminalAnsi("\uF115 agents");
    expect(html).toContain("agents");
    expect(html).not.toContain("\uF115");
  });

  it("collapses overly large vertical gaps from terminal redraw noise", () => {
    const html = renderTerminalAnsi("a\n\n\n\nb");
    expect(html).toContain("a\n\nb");
  });

  it("applies backspace redraw sequences so echoed commands do not duplicate", () => {
    const html = renderTerminalAnsi("l\bls\np\bpwd");
    expect(html).toContain("ls");
    expect(html).toContain("pwd");
    expect(html).not.toContain("lls");
    expect(html).not.toContain("ppwd");
  });

  it("removes standalone percent prompt artifacts", () => {
    const html = renderTerminalAnsi("%\nhello");
    expect(html).toContain("hello");
    expect(html).not.toContain(">%<");
    expect(html).not.toContain("%\nhello");
  });

  it("renders the leading workspace token in prompt lines as light blue", () => {
    const html = renderTerminalAnsi("mdif69dn5ocj ❯ ls");
    expect(html).toContain("mdif69dn5ocj");
    expect(html).toContain("color:rgb(85,255,255)");
  });
});
