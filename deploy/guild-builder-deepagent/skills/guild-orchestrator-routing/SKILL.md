---
name: guild-orchestrator-routing
description: Use this skill only for the main Deep Agent orchestrator. It defines which specialist subagent should handle each Guild-building concern, when to fan out work in parallel, and the phase gates that must be satisfied before publish.
allowed-tools: read_file, write_todos
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-orchestrator-routing

## Overview

This skill is for the supervisor only. It should not carry detailed Guild CLI,
SDK, integration, or publish knowledge. Its job is to route work to the right
specialist and keep the build sequential and reviewable.

## Supporting files

- `routing-map.md` maps user intents and build phases to specialist subagents

## Instructions

1. Read `routing-map.md`.
2. Maintain a clear phase order: understand request -> decompose -> choose templates -> CLI initialize -> edit agent code -> local validate -> repair loop -> publish/install -> live validate.
3. Delegate domain work to specialists instead of holding Guild details in the main prompt.
4. When two specialist tasks are independent, launch them in parallel in the same turn.
5. Stop for `request_checkpoint_review` at architecture, pre-publish, and post-publish boundaries instead of one-shotting the whole workflow.
6. Do not let publish start before tester/validator work says local validation is good enough and the pre-publish checkpoint is approved.
7. Use `documentation_specialist` only for an explicit workspace `README.md` need.
