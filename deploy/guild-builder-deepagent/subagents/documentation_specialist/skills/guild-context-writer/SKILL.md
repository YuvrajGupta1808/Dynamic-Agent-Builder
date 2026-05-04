---
name: guild-context-writer
description: Use this skill only when explicit context placement work is required. It compresses noisy documentation into high-signal authored context and should refresh official docs before workspace context publishing.
allowed-tools: read_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-context-writer

## Overview

This skill applies Deep Agents context-engineering rules to Guild workspace
projects.

## Supporting files

- `context-checklist.md` contains placement rules for memory, skills, shared context, and agent-specific context

## Instructions

1. Read `context-checklist.md`.
2. Under the default contract, prefer no extra workspace artifacts.
3. Put role-specific guidance in the agent folder only when explicitly needed.
4. Fetch official docs before running workspace context publish commands.
5. Update the workspace `README.md` only when the user explicitly wants operator-facing docs.
