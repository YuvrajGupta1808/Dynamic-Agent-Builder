---
name: guild-repair-loop
description: Use this skill when a Guild CLI validation, test, publish, or workspace command fails. It helps identify the smallest file change to make before rerunning the next command and should refresh official docs before uncommon remediation steps.
allowed-tools: execute, read_file, edit_file, write_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-repair-loop

## Overview

This skill keeps the Deep Agent in a tight diagnose-patch-rerun loop.

## Supporting files

- `failure-playbook.md` contains the repair-loop checklist

## Instructions

1. Read `failure-playbook.md`.
2. Capture stdout/stderr first.
3. Identify whether the issue is in prompt, context, code, or workspace setup.
4. Patch the smallest relevant file.
5. Refresh official docs before relying on uncommon remediation paths.
6. Rerun only the necessary command.
7. Keep validation output in chat unless the user explicitly asks for a file.
