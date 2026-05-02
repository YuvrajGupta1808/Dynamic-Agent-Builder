import { AnsiUp } from "ansi_up";

const ansi = new AnsiUp();

ansi.use_classes = false;

function stripUnsupportedGlyphs(text: string): string {
  return text
    .replace(/[\uE000-\uF8FF]/g, "")
    .replace(/[\u{F0000}-\u{FFFFD}]/gu, "")
    .replace(/[\u{100000}-\u{10FFFD}]/gu, "");
}

function applyBackspaces(text: string): string {
  const out: string[] = [];
  for (const char of text) {
    if (char === "\b") {
      out.pop();
      continue;
    }
    out.push(char);
  }
  return out.join("");
}

function normalizePromptArtifacts(text: string): string {
  return text
    .split("\n")
    .filter((line) => line.trim() !== "%")
    .map((line) => line.replace(/^([A-Za-z0-9._-]+)(\s+[❯›>])/, "\u001b[96m$1\u001b[0m$2"))
    .join("\n");
}

export function renderTerminalAnsi(text: string): string {
  // PTY streams often mix CRLF and bare carriage returns for prompt redraws.
  // Treat bare CR as cursor reset rather than a newline to avoid inflated spacing.
  const normalized = normalizePromptArtifacts(
    applyBackspaces(stripUnsupportedGlyphs(text.replace(/\r\n/g, "\n").replace(/\r/g, ""))),
  ).replace(/\n{3,}/g, "\n\n");
  return ansi.ansi_to_html(normalized);
}
