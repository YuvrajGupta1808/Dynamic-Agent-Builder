---
name: guild-agent-decomposition
description: Use this skill when a request needs to be decomposed into multiple Guild agents with distinct roles, boundaries, and ownership. It helps prevent unnecessary agent sprawl and should escalate to official docs only if the decomposition depends on exact Guild behavior.
allowed-tools: read_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-agent-decomposition

## Overview

This skill helps decide how many Guild agents a workspace actually needs and
what each agent should own.

## Supporting files

- `decision-checklist.md` contains decomposition rules and anti-patterns

## Instructions

1. Read `decision-checklist.md`.
2. Return the minimum viable agent set directly from the user request.
3. Assign each agent one clear role and boundary.
4. Avoid creating an extra orchestrator agent unless explicitly required.
5. If the decomposition depends on exact Guild runtime behavior, use `guild-official-docs` first.
