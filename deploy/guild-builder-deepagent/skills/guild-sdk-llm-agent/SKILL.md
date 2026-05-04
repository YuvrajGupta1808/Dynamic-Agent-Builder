---
name: guild-sdk-llm-agent
description: Use this skill when generating or reviewing a Guild LLM agent. It covers llmAgent structure, tool set guidance, and when to refresh from official docs before finalizing code.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-sdk-llm-agent

## Overview

This skill helps build prompt-driven Guild agents with `llmAgent`.

## Supporting files

- `implementation-checklist.md` contains the LLM-agent authoring checklist

## Instructions

1. Read `implementation-checklist.md`.
2. If the task depends on exact Guild SDK behavior, fetch the official docs using `guild-official-docs` first.
3. Keep the tool set minimal.
4. Prefer role clarity, prompt quality, and explicit handoff rules.
