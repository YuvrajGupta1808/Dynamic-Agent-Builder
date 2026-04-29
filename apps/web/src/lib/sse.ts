import type { StreamEvent } from "../types/api";

export function parseSseFrames(buffer: string): { events: StreamEvent[]; rest: string } {
  const events: StreamEvent[] = [];
  const frames = buffer.split(/\r?\n\r?\n/);
  const rest = frames.pop() ?? "";

  for (const frame of frames) {
    const lines = frame.split(/\r?\n/);
    const dataLines = lines.filter((line) => line.startsWith("data:"));
    if (!dataLines.length) continue;
    const payload = dataLines.map((line) => line.slice("data:".length)).join("\n").trim();
    if (!payload) continue;
    try {
      events.push(JSON.parse(payload) as StreamEvent);
    } catch {
      // Ignore malformed frames and keep consuming the stream.
      continue;
    }
  }

  return { events, rest };
}
