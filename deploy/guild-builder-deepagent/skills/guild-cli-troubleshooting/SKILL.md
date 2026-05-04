---
name: guild-cli-troubleshooting
description: Use this skill when Guild CLI commands fail because of auth, workspace selection, validation, or environment setup issues. It requires refreshing official docs before relying on uncommon troubleshooting flows.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-cli-troubleshooting

## Overview

This skill helps diagnose Guild CLI failures.

## Supporting files

- `troubleshooting-checklist.md` contains a failure triage checklist

## Instructions

1. Read `troubleshooting-checklist.md`.
2. Capture the exact failing command and its stderr/stdout.
3. Refresh official docs before relying on uncommon remediation paths.
4. Patch the smallest relevant file or environment assumption before retrying.
