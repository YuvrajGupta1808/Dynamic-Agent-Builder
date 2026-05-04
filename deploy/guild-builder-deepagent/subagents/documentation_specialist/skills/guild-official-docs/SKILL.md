---
name: guild-official-docs
description: Use this skill for any Guild AI implementation task that depends on exact CLI behavior, SDK/runtime details, integrations, triggers, workspace context publishing, versioning, or other details that may differ by topic. Fetch the official Guild docs index first, choose only the relevant pages, then read those pages before deciding commands or code.
allowed-tools: execute, read_file, write_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-official-docs

## Overview

This skill retrieves current Guild documentation from the official docs site.
Use it whenever precise Guild behavior matters more than heuristics.

## Supporting files

- `fetch-checklist.md` explains how to fetch and narrow the official docs
- `topic-map.md` maps common tasks to likely official documentation pages

## Instructions

1. Read `fetch-checklist.md`.
2. Fetch the official index at `https://docs.guild.ai/llms.txt`.
3. Choose only the relevant pages for the current task.
4. Fetch those pages before deciding commands or code.
5. Summarize the rules you will rely on before executing the Guild workflow.
6. Only materialize docs into the workspace if a long-running task would benefit from a local reference file.
7. Do not use `quick_search` or generic web search for Guild docs retrieval. Start from the official docs URLs directly.
