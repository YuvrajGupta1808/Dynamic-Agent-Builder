---
name: guild-sdk-auto-managed
description: Use this skill when generating or reviewing a Guild AUTO_MANAGED_STATE agent. It covers the procedural async run model, schema structure, and when to fetch official docs before writing non-LLM code.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-sdk-auto-managed

## Overview

This skill helps build procedural Guild agents using the auto-managed state
model.

## Supporting files

- `implementation-checklist.md` contains the auto-managed authoring checklist

## Instructions

1. Read `implementation-checklist.md`.
2. Always fetch official Guild docs before generating non-LLM agent code.
3. Verify that the workflow is sequential and does not need parallel tool rounds.
4. Record why auto-managed state fits better than LLM or BLANK.
