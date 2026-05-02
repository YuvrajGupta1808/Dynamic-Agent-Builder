#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


BASE_URL = "http://127.0.0.1:8000"
TOKEN = "dev-local-token"
MODEL = "openai:accounts/fireworks/models/glm-4p7"
MODE = "accept_everything"

PROMPTS = [
    "Create a healthcare support workspace with appointment help, insurance FAQ triage, and emergency handoff rules. Keep all specialist agent roles explicit.",
    "Design an e-commerce support workspace for order tracking, cancellations, damaged-item refunds, and escalation to a human agent with SLA tiers.",
    "Build a SaaS onboarding + support workspace that handles account setup issues, billing disputes, feature guidance, and escalation to technical support.",
    "Create a telecom support workspace for plan changes, billing corrections, outage reporting, and fraud escalation with strict verification steps.",
    "Build an education support workspace for admissions FAQs, fee-payment issues, scholarship queries, and counselor escalation workflows.",
    "Create a travel support workspace for booking changes, refund eligibility, lost baggage assistance, and urgent human escalation during active trips.",
    "Build a fintech support workspace for transaction disputes, failed transfers, KYC document help, and compliance-aware escalation to human review.",
]


def _json_request(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _stream(session_id: str, prompt: str) -> tuple[list[dict[str, Any]], float]:
    req = urllib.request.Request(
        f"{BASE_URL}/api/sessions/{session_id}/runs/stream",
        data=json.dumps({"message": prompt, "model": MODEL, "mode": MODE}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    started = time.time()
    events: list[dict[str, Any]] = []
    with urllib.request.urlopen(req, timeout=900) as resp:
        buf: list[str] = []
        while True:
            line = resp.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            if text == "":
                if not buf:
                    continue
                raw = "\n".join(buf)
                buf = []
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                events.append(event)
                continue
            if text.startswith("data:"):
                buf.append(text[5:].lstrip())
    return events, round(time.time() - started, 2)


def _summarize(events: list[dict[str, Any]], duration_s: float, prompt: str, idx: int) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    tool_calls: list[str] = []
    subagents: list[str] = []
    done_message = ""
    errors: list[str] = []
    for e in events:
        t = str(e.get("type") or "")
        by_type[t] = by_type.get(t, 0) + 1
        if t == "tool_call":
            data = e.get("data") or {}
            name = str(data.get("name") or "")
            if name:
                tool_calls.append(name)
        if t == "subagent":
            source = str(e.get("source") or "")
            if source and source not in subagents:
                subagents.append(source)
        if t == "done":
            done_message = str(e.get("message") or "")
        if t == "error":
            errors.append(str(e.get("message") or ""))
    return {
        "index": idx,
        "prompt": prompt,
        "durationSec": duration_s,
        "eventCounts": by_type,
        "toolCallsUnique": sorted(set(tool_calls)),
        "toolCallsTotal": len(tool_calls),
        "subagentsSeen": subagents,
        "doneMessage": done_message,
        "errors": errors,
        "ok": len(errors) == 0 and done_message.lower().startswith("run complete"),
    }


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path("/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs") / f"seven-prompts-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    workspace_name = f"seven-prompts-{stamp.lower()}"
    _json_request("/api/workspaces", {"name": workspace_name})
    session = _json_request(
        "/api/sessions",
        {
            "workspaceMode": "local",
            "workspace": workspace_name,
            "model": MODEL,
            "mode": MODE,
        },
    )
    session_id = str(session["id"])

    all_summaries: list[dict[str, Any]] = []
    for i, prompt in enumerate(PROMPTS, start=1):
        events, duration_s = _stream(session_id, prompt)
        summary = _summarize(events, duration_s, prompt, i)
        all_summaries.append(summary)
        (out_dir / f"run-{i:02d}-events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
        (out_dir / f"run-{i:02d}-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"[{i}/7] ok={summary['ok']} duration={duration_s}s events={len(events)} subagents={','.join(summary['subagentsSeen']) or '-'}")

    batch_summary = {
        "workspace": workspace_name,
        "sessionId": session_id,
        "model": MODEL,
        "mode": MODE,
        "runs": all_summaries,
        "passed": sum(1 for r in all_summaries if r["ok"]),
        "failed": sum(1 for r in all_summaries if not r["ok"]),
        "generatedAt": stamp,
        "outputDir": str(out_dir),
    }
    (out_dir / "batch-summary.json").write_text(json.dumps(batch_summary, indent=2), encoding="utf-8")
    print(f"Output directory: {out_dir}")
    print(json.dumps({"passed": batch_summary["passed"], "failed": batch_summary["failed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

