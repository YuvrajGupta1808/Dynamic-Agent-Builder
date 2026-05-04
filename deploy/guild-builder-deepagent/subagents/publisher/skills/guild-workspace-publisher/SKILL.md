---
name: guild-workspace-publisher
description: Use this skill when published Guild agents need to be installed into a Guild workspace, shared context must be published, or live workspace chats need to be validated. It should refresh official docs before workspace publishing or trigger flows.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-workspace-publisher

## Overview

This skill handles the Guild workspace steps after local agent validation.

## Supporting files

- `workspace-checklist.md` contains the installation and validation checklist

## Instructions

1. Read `workspace-checklist.md`.
2. Create or select the Guild workspace.
3. Install validated agents.
4. Fetch official docs before shared context publish or trigger work.
5. Publish shared workspace context if required.
6. Run representative chats and record outcomes.
7. When the user wants evidence, keep the post-publish notes focused on representative input/output behavior.
