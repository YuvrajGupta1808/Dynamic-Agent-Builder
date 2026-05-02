# 7-Prompt Orchestrator Evaluation (Accept Everything)

## Scope

This evaluation runs the orchestrator on 7 support-domain prompts using:

- model: `openai:accounts/fireworks/models/glm-4p7`
- mode: `accept_everything`
- backend API stream endpoint: `POST /api/sessions/{session_id}/runs/stream`
- log capture: raw SSE events + per-run summaries

## How Testing Was Executed

Runner script:

- [/Users/Yuvraj/Dynamic-Agent-Builder/backend/scripts/run_seven_prompts.py](/Users/Yuvraj/Dynamic-Agent-Builder/backend/scripts/run_seven_prompts.py)

Execution flow per batch:

1. Create workspace via `POST /api/workspaces`.
2. Create one session via `POST /api/sessions` with `mode=accept_everything`.
3. Run each prompt via stream endpoint.
4. Save:
   - `run-XX-events.json` (full event stream)
   - `run-XX-summary.json` (counts + status)
   - `batch-summary.json` (aggregate)

## Batch Metadata

- Workspace: `seven-prompts-20260501t053650z`
- Session ID: `30d77937bb1048c993e4d478ae83e131`
- Output directory:
  [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z)
- Aggregate result: `passed=7`, `failed=0`

## Test Prompts

1. Healthcare support workspace with appointments, insurance triage, emergency handoff.
2. E-commerce support workspace with tracking, cancellation, damaged refunds, SLA escalation.
3. SaaS onboarding/support workspace with setup, billing disputes, feature guidance, tech escalation.
4. Telecom support workspace with plan changes, billing corrections, outages, fraud escalation.
5. Education support workspace with admissions, fee issues, scholarships, counselor escalation.
6. Travel support workspace with booking changes, refunds, lost baggage, urgent escalation.
7. Fintech support workspace with disputes, failed transfers, KYC help, compliance escalation.

## Per-Run Results

| Run | Duration (s) | Status | Subagents Seen | Tool Calls (total) | Key Tool Calls |
|---|---:|---|---|---:|---|
| 1 | 16.94 | pass | specialist, decomposer, template_selector | 10 | task, SpecialistReport, request_checkpoint_review |
| 2 | 18.87 | pass | specialist, decomposer, template_selector | 10 | task, SpecialistReport, request_checkpoint_review |
| 3 | 18.56 | pass | specialist, decomposer, template_selector | 10 | task, SpecialistReport, request_checkpoint_review |
| 4 | 46.13 | pass | specialist, decomposer, template_selector | 22 | task, read_file, glob, SpecialistReport, request_checkpoint_review |
| 5 | 19.20 | pass | specialist, decomposer, template_selector | 12 | task, SpecialistReport, request_checkpoint_review |
| 6 | 39.31 | pass | specialist, decomposer, template_selector | 26 | task, ls, read_file, write_todos, SpecialistReport, request_checkpoint_review |
| 7 | 26.92 | pass | specialist, decomposer, template_selector | 14 | task, ls, read_file, SpecialistReport, request_checkpoint_review |

Source of truth:

- [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/batch-summary.json](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/batch-summary.json)

## Streaming / Thinking / Tool-Call Logs

Full event streams are stored here:

- Run 01: [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-01-events.json](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-01-events.json)
- Run 02: [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-02-events.json](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-02-events.json)
- Run 03: [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-03-events.json](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-03-events.json)
- Run 04: [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-04-events.json](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-04-events.json)
- Run 05: [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-05-events.json](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-05-events.json)
- Run 06: [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-06-events.json](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-06-events.json)
- Run 07: [/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-07-events.json](/Users/Yuvraj/Dynamic-Agent-Builder/.data/eval-logs/seven-prompts-20260501T053650Z/run-07-events.json)

Each file includes:

- `thinking` events from orchestrator/subagents
- `tool_call` events with names/arguments
- `subagent` lifecycle/progress events
- `token` stream output
- `done` / `error` terminal events

## Publish / Guild Dashboard Clarification

In this batch, no explicit Guild publish/install action was executed. The logs show planning/decomposition/template selection flows and checkpoint review calls, but **no concrete dashboard publish step**.

That is why you do not see created/updated agents on Guild AI dashboard from these runs.

If you want dashboard-visible artifacts, the prompt must explicitly include:

1. workspace install/publish phase,
2. concrete publish command/tool invocation,
3. post-publish verification against Guild workspace/session.

## Notes on “test / validate / push” visibility

For this run set:

- “test/validate” appears as planning + structured subagent reports + checkpoint requests.
- “push/publish” was not executed in these 7 prompts.
- To force those phases, add explicit instruction: “execute publish and verify in Guild dashboard, then return publish IDs and URLs.”
