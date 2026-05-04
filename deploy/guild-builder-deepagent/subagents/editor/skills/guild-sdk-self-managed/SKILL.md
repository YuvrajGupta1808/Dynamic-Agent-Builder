---
name: guild-sdk-self-managed
description: Use this skill when generating or reviewing a Guild self-managed agent from the BLANK template. It covers explicit state, start/onToolResults flow, and when to fetch official docs before implementing advanced orchestration.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-sdk-self-managed

## Overview

This skill helps build explicit state-machine Guild agents.

## Supporting files

- `implementation-checklist.md` contains the self-managed authoring checklist

## Instructions

1. Read `implementation-checklist.md`.
2. Always fetch official Guild docs before implementing self-managed state logic.
3. Use this only when explicit lifecycle control or parallel tool calls are truly required.
4. Record the state model and transition reasoning in the agent docs.
