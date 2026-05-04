---
name: guild-publish-and-versions
description: Use this skill when saving, validating, publishing, or reviewing Guild agent versions. It covers save/publish/version flows and requires refreshing official docs before final publish decisions.
allowed-tools: execute, read_file, write_file, edit_file
metadata:
  domain: guild-builder
  version: "1.0"
---

# guild-publish-and-versions

## Overview

This skill handles Guild save, validate, publish, and version management work.

## Supporting files

- `publish-checklist.md` contains the publish/version checklist

## Instructions

1. Read `publish-checklist.md`.
2. Refresh the official docs before save/publish/versioning work when exact behavior matters.
3. Separate local validation from publish decisions.
4. Record publish outcomes and version assumptions in project docs.
5. Keep post-publish validation evidence focused on representative input/output behavior.
