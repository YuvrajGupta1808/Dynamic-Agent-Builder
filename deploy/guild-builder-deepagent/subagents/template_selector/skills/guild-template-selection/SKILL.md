---
name: guild-template-selection
description: Use this skill when deciding which Guild agent template to use. It maps requested behavior to LLM, AUTO_MANAGED_STATE, or BLANK with a written justification in chat, and it should refresh official docs before non-LLM agent generation.
allowed-tools: read_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-template-selection

## Overview

This skill selects the right Guild template by capability analysis rather than
habit.

## Supporting files

- `selection-matrix.md` contains the template decision matrix

## Instructions

1. Read `selection-matrix.md`.
2. Identify whether the job is prompt-driven, sequential, or explicitly stateful.
3. If the likely answer is not `LLM`, fetch official Guild docs first.
4. Return the chosen template and reasoning in the response.
5. Record rejected alternatives briefly.
