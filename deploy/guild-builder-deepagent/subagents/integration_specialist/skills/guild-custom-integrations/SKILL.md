---
name: guild-custom-integrations
description: Use this skill when designing a custom Guild integration for a service that is not covered by a first-party integration. It requires reading the official custom integration docs before proposing schemas, auth, endpoints, or webhook behavior.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-custom-integrations

## Overview

This skill helps design custom Guild integrations.

## Supporting files

- `custom-integration-checklist.md` contains design steps and safety checks

## Instructions

1. Read `custom-integration-checklist.md`.
2. Always fetch official Guild docs before custom integration design.
3. Confirm that a first-party integration is not sufficient.
4. Document auth, endpoints, webhook expectations, and versioning assumptions before generating implementation artifacts.
