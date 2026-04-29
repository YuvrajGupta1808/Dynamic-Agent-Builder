import { describe, expect, it } from "vitest";

import { parseSseFrames } from "./sse";

describe("parseSseFrames", () => {
  it("parses complete frames and preserves the partial tail", () => {
    const input =
      'event: token\ndata: {"type":"token","runId":"r","sessionId":"s","sequence":1,"source":"main","message":"hi","data":{}}\n\n' +
      'event: done\ndata: {"type":"done","runId":"r","sessionId":"s","sequence":2,"source":"main","message":"ok","data":{}}';

    const parsed = parseSseFrames(input);

    expect(parsed.events).toHaveLength(1);
    expect(parsed.events[0].type).toBe("token");
    expect(parsed.rest).toContain("event: done");
  });
});

