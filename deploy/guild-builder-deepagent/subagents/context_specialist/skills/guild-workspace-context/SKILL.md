---
name: guild-workspace-context
description: Use this skill when writing, publishing, or reviewing Guild workspace context. It covers what belongs in shared context, when to fetch official docs, and how to avoid bloated context files.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-workspace-context

## Overview

This skill helps write concise shared Guild workspace context.

## Supporting files

- `context-checklist.md` contains scope and publishing guidance

## Instructions

1. Read `context-checklist.md`.
2. Fetch official Guild docs before running workspace context publish flows.
3. Keep only cross-agent facts in shared workspace context.
4. Put role-specific guidance in per-agent files, not shared context.
