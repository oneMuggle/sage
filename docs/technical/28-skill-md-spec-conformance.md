# 28. SKILL.md Spec Conformance (agentskills.io)

> **Status**: Implemented (2026-06-29)
> **Spec reference**: <https://agentskills.io/specification>

## Overview

`backend/skills/skill_md/` now fully conforms to the agentskills.io open specification, while preserving all 8 sage business extensions. This document describes the alignment, new fields, and migration notes.

## What Changed

### New spec-optional fields

| Field | Type | Constraint | Default |
|---|---|---|---|
| `license` | `str` | non-empty (when present) | `None` |
| `compatibility` | `str` | ≤500 chars | `None` |
| `allowed-tools` | `str` (space-separated; parsed to tuple by loader) | non-string raises | `()` |

### Strengthened validation

- `name`: 1-64 chars (spec: Max 64 characters) — was 1+ chars (no upper bound)
- `description`: 1-1024 chars (spec: Max 1024 characters) — was 1+ chars (no upper bound)
- `description`: warning emitted if no trigger keyword detected (`use this`, `when `, `use `, `用`, `何时`, `用来`)

### New file form

- Single-file form `<dir>/SKILL.md` now supported (was: only `<dir>/<name>/SKILL.md`)
- Priority: builtin > subdirectory form > single-file form

### Soft constraint (warning, not error)

- `name` should match parent directory name (spec: "Must match the parent directory name"). sage warns but does not block, to preserve historical SKILL.md naming.

## Example: spec-compliant SKILL.md

```yaml
---
name: pdf-reader
description: Use this when the user asks to read or extract text from PDF files
license: Apache-2.0
compatibility: Requires Python 3.10+
metadata:
  author: sage-team
  version: 1.0.0
allowed-tools: Bash Read
---
# PDF Reader

This skill reads PDF files using pypdf.
```

## Migration Notes

- **No migration required** for existing SKILL.md files: all new fields are optional and have backward-compatible defaults.
- **Strongly recommended**: add `license` and `compatibility` to your SKILL.md for ecosystem interop.
- **Optional**: rename parent directories to match frontmatter `name` to silence the name-vs-parent warning.

## Current scope

- `allowed-tools` is parsed and exposed as metadata; tool-gateway enforcement is not part of the current adapter contract.
- `python -m backend.cli.skills lint` validates discovered or explicitly supplied SKILL.md roots using the same lightweight parser as `sage doctor`.
- A user-facing authoring guide is available at [`../user-manual/04-skill-md-authoring.md`](../user-manual/04-skill-md-authoring.md).

## Related Documents

- `docs/technical/24-skills-system.md` — original skills architecture (now appends "Spec Conformance" subsection)
- `docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md` — design spec (实施细节已并入 24-skills-system.md §"Spec Conformance"，对应 implementation plan 已归档删除)
