---
name: guild-cli-runbook
description: Use this skill when running or planning Guild CLI commands for agent scaffolding, testing, publishing, workspace installation, and chat validation. It should escalate to official docs before uncommon commands or exact CLI edge cases.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-cli-runbook

## Overview

This skill provides the command flow for local Guild agent project work and
workspace-level Guild operations.

## Supporting files

- `commands.md` lists common per-agent and workspace-level commands

## Instructions

1. Read `commands.md`.
2. Run agent-folder commands from the correct agent directory.
3. Run workspace commands only after agents validate locally.
4. Do not create side-artifact reports by default.
5. Fetch official docs before uncommon Guild commands or when exact CLI behavior matters.
6. Do not run repeated `guild --help` commands for common flows already covered by workspace memory or this runbook.
