# AgentSkills.io Spec Conformance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align `backend/skills/skill_md/` with the [agentskills.io open specification](https://agentskills.io/specification) by adding 3 optional spec fields, strengthening name/description length validation, supporting single-file SKILL.md form, and warning on name-vs-parent-dir mismatch — all forward-compatible (no breaking changes) and preserving all 8 sage business extensions.

**Architecture:** 7 bite-sized tasks across 3 modules. Each task is one independent TDD cycle ending with a single commit. Order: frontmatter validators → skill dataclass fields → loader integration → single-file form → E2E → docs. Every step is additive; existing SKILL.md files continue to load.

**Tech Stack:** Python 3.10+ (sage-backend conda env at `/home/fz/anaconda3/envs/sage-backend`), `pyyaml==6.0.1`, `pytest` with `pytest-cov`, `vitest` for TS smoke (no new deps).

## Global Constraints

- **Python env**: All tests must run inside `sage-backend` conda env. Use `/home/fz/anaconda3/envs/sage-backend/bin/python` (NOT system `python3`).
- **Commit style**: Conventional Commits (`feat:` / `docs:` / `test:` / `refactor:`). Attribution disabled globally; do not add `Co-Authored-By` trailers.
- **Working branch**: `main`. **Do NOT** commit to `release/win7` (cherry-pick only on user request).
- **No new dependencies**: Continue using `pyyaml==6.0.1` already in `backend/requirements.txt`.
- **No mutation of builtin skills**: `backend/skills/builtin/` is not loaded by `skill_md/loader`; this plan only touches `skill_md/`.
- **Backward compatibility**: All changes are additive. Existing SKILL.md files (no `license` / `compatibility` / `allowed-tools`) must continue to load without modification.
- **Spec reference**: All field names and constraints come from <https://agentskills.io/specification>.

---

## File Structure

**Modified files (3):**

| File | Role in this plan |
|---|---|
| `backend/skills/skill_md/frontmatter.py` | Add 3 new `_validate_*` functions; strengthen `_validate_name` and `_validate_description` with length + trigger-keyword checks; integrate new validators into `parse()`. |
| `backend/skills/skill_md/skill.py` | Add 3 new fields to `SkillMdDocument` dataclass: `license: str \| None`, `compatibility: str \| None`, `allowed_tools: tuple[str, ...]`. |
| `backend/skills/skill_md/loader.py` | Add `name != parent_dir.name` warning; parse `allowed-tools` into `tuple`; support single-file `<dir>/SKILL.md` form; pass new fields into `SkillMdDocument` constructor. |

**New files (4):**

| File | Role |
|---|---|
| `backend/tests/skills/skill_md/test_frontmatter_compliance.py` | Unit tests for new validators (Task 1 + Task 2). |
| `backend/tests/skills/skill_md/test_skillmd_doc.py` | Unit tests for new `SkillMdDocument` fields (Task 3). |
| `backend/tests/skills/skill_md/test_loader_compliance.py` | Integration tests for loader new behavior (Task 4 + Task 5). |
| `tests/electron/skillmd-compliance.spec.ts` | E2E smoke test for full skill load via Electron app (Task 6). |

**Documentation files (2):**

| File | Role |
|---|---|
| `docs/technical/31-skill-md-spec-conformance.md` | New technical doc explaining spec alignment, new fields, migration. |
| `docs/technical/07-skills.md` | Existing doc; append "Spec Conformance" subsection. |
| `CHANGELOG.md` | Add Unreleased entry. |

---

## Task 1: Strengthen `name` and `description` length validation + trigger keyword warning

**Files:**
- Modify: `backend/skills/skill_md/frontmatter.py:85-99` (`_validate_name` and `_validate_description`)
- Test: `backend/tests/skills/skill_md/test_frontmatter_compliance.py` (new file)

**Interfaces:**
- Consumes: existing `_validate_name(name: Any) -> str` and `_validate_description(description: Any) -> str` signatures (must remain identical)
- Produces: same signatures but with stricter checks:
  - `_validate_name` raises `SkillMdParseError` if `len(name) > 64`
  - `_validate_description` raises `SkillMdParseError` if `len(description) > 1024`
  - `_validate_description` emits a `logger.warning` if description lacks any of: `"use this"`, `"when "`, `"use "`, `"用"`, `"何时"`, `"用来"` (case-insensitive)

- [ ] **Step 1: Create test file with 6 failing tests**

Create `backend/tests/skills/skill_md/test_frontmatter_compliance.py`:

```python
"""Tests for agentskills.io spec compliance (Task 1 + Task 2).

Covers:
  - name length 1-64 chars
  - description length 1-1024 chars
  - description trigger-keyword warning
  - license / compatibility / allowed-tools field validation
"""

from __future__ import annotations

import logging
import pytest

from backend.skills.skill_md.frontmatter import (
    SkillMdParseError,
    parse,
)


# ---- name length (Task 1) ----

def test_name_at_max_length_64_passes():
    text = "---\nname: " + "a" * 64 + "\ndescription: a tool\n---\nbody"
    meta, body = parse(text)
    assert meta["name"] == "a" * 64


def test_name_over_max_length_64_raises():
    text = "---\nname: " + "a" * 65 + "\ndescription: a tool\n---\nbody"
    with pytest.raises(SkillMdParseError, match="1-64 chars"):
        parse(text)


# ---- description length (Task 1) ----

def test_description_at_max_length_1024_passes():
    text = "---\nname: x\ndescription: " + "d" * 1024 + "\n---\nbody"
    meta, body = parse(text)
    assert len(meta["description"]) == 1024


def test_description_over_max_length_1024_raises():
    text = "---\nname: x\ndescription: " + "d" * 1025 + "\n---\nbody"
    with pytest.raises(SkillMdParseError, match="1-1024 chars"):
        parse(text)


# ---- description trigger keyword warning (Task 1) ----

def test_description_with_trigger_keyword_passes_silently(caplog):
    text = "---\nname: x\ndescription: Use this when you need to search files\n---\nbody"
    with caplog.at_level(logging.WARNING, logger="backend.skills.skill_md.frontmatter"):
        parse(text)
    assert "lacks trigger keywords" not in caplog.text


def test_description_without_trigger_keyword_warns(caplog):
    text = "---\nname: x\ndescription: A search tool for files\n---\nbody"
    with caplog.at_level(logging.WARNING, logger="backend.skills.skill_md.frontmatter"):
        parse(text)
    assert "lacks trigger keywords" in caplog.text
```

- [ ] **Step 2: Run tests, expect Task 1 over-limit tests to FAIL**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_frontmatter_compliance.py -v`

Expected:
- `test_name_at_max_length_64_passes` PASSES
- `test_name_over_max_length_64_raises` FAILS (no length check yet)
- `test_description_at_max_length_1024_passes` PASSES
- `test_description_over_max_length_1024_raises` FAILS (no length check yet)
- `test_description_with_trigger_keyword_passes_silently` PASSES
- `test_description_without_trigger_keyword_warns` FAILS (no warning emitted yet)

- [ ] **Step 3: Strengthen `_validate_name` in `frontmatter.py`**

Replace `backend/skills/skill_md/frontmatter.py:85-93` (`_validate_name`):

```python
def _validate_name(name: Any) -> str:
    """校验 name 是合法 slug(小写字母/数字/连字符),长度 1-64 (agentskills.io spec)。"""
    if not isinstance(name, str) or not name:
        raise SkillMdParseError("frontmatter 'name' must be a non-empty string")
    if not (1 <= len(name) <= 64):
        raise SkillMdParseError(
            f"frontmatter 'name' must be 1-64 chars, got {len(name)} chars: {name!r}"
        )
    if not _NAME_SLUG_RE.match(name):
        raise SkillMdParseError(
            f"frontmatter 'name' must be a slug (lowercase letters/digits/hyphens), got: {name!r}"
        )
    return name
```

- [ ] **Step 4: Add logger import + strengthen `_validate_description` in `frontmatter.py`**

First, add `import logging` near the top of `backend/skills/skill_md/frontmatter.py` (after `import re` line 24):

```python
import logging

logger = logging.getLogger(__name__)
```

Then replace `backend/skills/skill_md/frontmatter.py:96-99` (`_validate_description`):

```python
# Description 触发关键词 (agentskills.io spec 建议,大小写不敏感)
_TRIGGER_HINTS = ("use this", "when ", "use ", "用", "何时", "用来")


def _validate_description(description: Any) -> str:
    """校验 description 非空且长度 1-1024 (agentskills.io spec),含触发关键词时静默,否则 warning。"""
    if not isinstance(description, str) or not description:
        raise SkillMdParseError("frontmatter 'description' must be a non-empty string")
    if not (1 <= len(description) <= 1024):
        raise SkillMdParseError(
            f"frontmatter 'description' must be 1-1024 chars, got {len(description)} chars"
        )
    if not any(h in description.lower() for h in _TRIGGER_HINTS):
        logger.warning(
            "frontmatter 'description' for skill lacks trigger keywords; "
            "agents may not recognize when to invoke this skill (description=%r)",
            description[:60],
        )
    return description
```

- [ ] **Step 5: Run Task 1 tests, expect all 6 to PASS**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_frontmatter_compliance.py -v`

Expected: all 6 Task 1 tests PASS.

- [ ] **Step 6: Run existing skill_md tests, expect zero regression**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/ -v`

Expected: all existing tests still pass.

- [ ] **Step 7: Commit Task 1**

```bash
cd /home/fz/project/sage
git add backend/skills/skill_md/frontmatter.py backend/tests/skills/skill_md/test_frontmatter_compliance.py
git commit -m "feat(skill-md): enforce name 1-64 + description 1-1024 + trigger keyword warning

Align frontmatter validation with agentskills.io spec section 'name' and
'description' field constraints.

- name: add 1-64 char length check (spec: Max 64 characters)
- description: add 1-1024 char length check (spec: Max 1024 characters)
- description: emit warning when no trigger keyword detected
  (spec: 'Should include specific keywords that help agents identify
  relevant tasks'); keywords: 'use this', 'when ', 'use ', '用', '何时', '用来'

Warning does not block loading; only validators are stricter.

Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md
Refs: https://agentskills.io/specification"
```

---

## Task 2: Add 3 new spec optional fields (`license`, `compatibility`, `allowed-tools`)

**Files:**
- Modify: `backend/skills/skill_md/frontmatter.py` (add 3 new `_validate_*` functions; integrate into `parse()`)
- Test: `backend/tests/skills/skill_md/test_frontmatter_compliance.py` (append more tests)

**Interfaces:**
- Consumes: existing `parse(text: str) -> tuple[dict[str, Any], str]` signature
- Produces: 3 new optional fields in the returned `meta` dict:
  - `license: str` (when present, non-empty)
  - `compatibility: str` (when present, ≤500 chars)
  - `allowed-tools: str` (when present, space-separated; preserved as string in frontmatter, parsing to tuple happens in `loader.py` Task 4)

- [ ] **Step 1: Append 8 more tests to `test_frontmatter_compliance.py`**

Append the following to `backend/tests/skills/skill_md/test_frontmatter_compliance.py`:

```python
# ---- license (Task 2) ----

def test_license_optional_default_absent():
    text = "---\nname: x\ndescription: A tool\n---\nbody"
    meta, _ = parse(text)
    assert "license" not in meta


def test_license_non_empty_string_passes():
    text = "---\nname: x\ndescription: A tool\nlicense: MIT\n---\nbody"
    meta, _ = parse(text)
    assert meta["license"] == "MIT"


def test_license_empty_string_raises():
    text = '---\nname: x\ndescription: A tool\nlicense: ""\n---\nbody'
    with pytest.raises(SkillMdParseError, match="license"):
        parse(text)


# ---- compatibility (Task 2) ----

def test_compatibility_optional_default_absent():
    text = "---\nname: x\ndescription: A tool\n---\nbody"
    meta, _ = parse(text)
    assert "compatibility" not in meta


def test_compatibility_under_500_chars_passes():
    text = "---\nname: x\ndescription: A tool\ncompatibility: " + "c" * 499 + "\n---\nbody"
    meta, _ = parse(text)
    assert len(meta["compatibility"]) == 499


def test_compatibility_over_500_chars_raises():
    text = "---\nname: x\ndescription: A tool\ncompatibility: " + "c" * 501 + "\n---\nbody"
    with pytest.raises(SkillMdParseError, match="compatibility"):
        parse(text)


# ---- allowed-tools (Task 2) ----

def test_allowed_tools_optional_default_absent():
    text = "---\nname: x\ndescription: A tool\n---\nbody"
    meta, _ = parse(text)
    assert "allowed-tools" not in meta


def test_allowed_tools_passes():
    text = "---\nname: x\ndescription: A tool\nallowed-tools: Bash Read Write\n---\nbody"
    meta, _ = parse(text)
    assert meta["allowed-tools"] == "Bash Read Write"


# ---- full spec example (Task 2) ----

def test_full_spec_compliant_frontmatter():
    """agentskills.io 官方示例字段全填,全部解析成功。"""
    text = """---
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

This skill reads PDF files.
"""
    meta, body = parse(text)
    assert meta["name"] == "pdf-reader"
    assert "extract text" in meta["description"]
    assert meta["license"] == "Apache-2.0"
    assert meta["compatibility"] == "Requires Python 3.10+"
    assert meta["metadata"]["author"] == "sage-team"
    assert meta["allowed-tools"] == "Bash Read"
    assert body.startswith("# PDF Reader")
```

- [ ] **Step 2: Run tests, expect 2 tests to FAIL**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_frontmatter_compliance.py -v`

Expected: 12 of 14 PASS; 2 FAIL:
- `test_compatibility_over_500_chars_raises` (no length check yet)
- `test_license_empty_string_raises` (no emptiness check yet)

- [ ] **Step 3: Add 3 new validator functions to `frontmatter.py`**

Add the following after the `_validate_command_dispatch` function (around `frontmatter.py:162`):

```python
def _validate_license(license_field: Any) -> str | None:
    """校验 license 字段(agentskills.io spec, optional)。

    Args:
        license_field: 来自 YAML 的值(可能为 None)。

    Returns:
        非空字符串,或 None(字段未提供时)。

    Raises:
        SkillMdParseError: 提供了 license 但不是非空字符串。
    """
    if license_field is None:
        return None
    if not isinstance(license_field, str) or not license_field:
        raise SkillMdParseError(
            f"frontmatter 'license' must be a non-empty string, got {license_field!r}"
        )
    return license_field


def _validate_compatibility(compat: Any) -> str | None:
    """校验 compatibility 字段(agentskills.io spec, optional, ≤500 字符)。

    Args:
        compat: 来自 YAML 的值(可能为 None)。

    Returns:
        字符串,或 None(字段未提供时)。

    Raises:
        SkillMdParseError: 提供了但不是字符串,或长度超过 500 字符。
    """
    if compat is None:
        return None
    if not isinstance(compat, str):
        raise SkillMdParseError(
            f"frontmatter 'compatibility' must be a string, got {type(compat).__name__}"
        )
    if len(compat) > 500:
        raise SkillMdParseError(
            f"frontmatter 'compatibility' must be <= 500 chars (spec), got {len(compat)} chars"
        )
    return compat


def _validate_allowed_tools(tools: Any) -> str | None:
    """校验 allowed-tools 字段(agentskills.io spec, optional, 空格分隔字符串)。

    注: 解析为 tuple 由 loader.py Task 4 完成;此处只校验原始字符串类型。

    Args:
        tools: 来自 YAML 的值(可能为 None)。

    Returns:
        字符串,或 None(字段未提供时)。

    Raises:
        SkillMdParseError: 提供了但不是字符串。
    """
    if tools is None:
        return None
    if not isinstance(tools, str):
        raise SkillMdParseError(
            f"frontmatter 'allowed-tools' must be a string, got {type(tools).__name__}"
        )
    return tools
```

- [ ] **Step 4: Integrate 3 new validators into `parse()`**

Replace the v2 field validation block in `frontmatter.py:201-204`:

```python
    # v2 字段校验
    _validate_requires(meta.get("requires"))
    _validate_os(meta.get("os"))
    _validate_always(meta.get("always"))
    _validate_command_dispatch(meta.get("command-dispatch"))
```

With:

```python
    # v2 字段校验
    _validate_requires(meta.get("requires"))
    _validate_os(meta.get("os"))
    _validate_always(meta.get("always"))
    _validate_command_dispatch(meta.get("command-dispatch"))

    # agentskills.io spec 可选字段 (Task 2)
    _validate_license(meta.get("license"))
    _validate_compatibility(meta.get("compatibility"))
    _validate_allowed_tools(meta.get("allowed-tools"))
```

- [ ] **Step 5: Run all `test_frontmatter_compliance.py` tests, expect 14 PASS**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_frontmatter_compliance.py -v`

Expected: all 14 tests PASS (6 from Task 1 + 8 from Task 2).

- [ ] **Step 6: Run all skill_md tests, expect zero regression**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/ -v`

Expected: all existing tests still pass.

- [ ] **Step 7: Commit Task 2**

```bash
cd /home/fz/project/sage
git add backend/skills/skill_md/frontmatter.py backend/tests/skills/skill_md/test_frontmatter_compliance.py
git commit -m "feat(skill-md): add agentskills.io optional fields (license/compatibility/allowed-tools)

Add 3 new spec-compliant optional fields to SKILL.md frontmatter:

- license (str, non-empty): SPDX-style identifier or full license name
- compatibility (str, <=500 chars per spec): environment requirements
- allowed-tools (str, space-separated): tools the skill may use
  (parsed to tuple by loader in Task 4)

All 3 fields are optional; existing SKILL.md files without them
continue to load without modification.

Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md
Refs: https://agentskills.io/specification#frontmatter"
```

---

## Task 3: Add 3 new fields to `SkillMdDocument` dataclass

**Files:**
- Modify: `backend/skills/skill_md/skill.py:49-67` (`SkillMdDocument` dataclass)
- Test: `backend/tests/skills/skill_md/test_skillmd_doc.py` (new file)

**Interfaces:**
- Consumes: existing `SkillMdDocument` dataclass
- Produces: 3 new fields with defaults:
  - `license: str | None = None`
  - `compatibility: str | None = None`
  - `allowed_tools: tuple[str, ...] = ()`

- [ ] **Step 1: Create test file with 5 failing tests**

Create `backend/tests/skills/skill_md/test_skillmd_doc.py`:

```python
"""Tests for SkillMdDocument dataclass (Task 3: new spec fields)."""

from __future__ import annotations

from backend.skills.skill_md.skill import SkillMdDocument


def test_default_license_is_none():
    doc = SkillMdDocument(name="x", description="A tool")
    assert doc.license is None


def test_default_compatibility_is_none():
    doc = SkillMdDocument(name="x", description="A tool")
    assert doc.compatibility is None


def test_default_allowed_tools_is_empty_tuple():
    doc = SkillMdDocument(name="x", description="A tool")
    assert doc.allowed_tools == ()


def test_set_new_fields():
    doc = SkillMdDocument(
        name="x",
        description="A tool",
        license="MIT",
        compatibility="Requires Python 3.10+",
        allowed_tools=("Bash", "Read", "Write"),
    )
    assert doc.license == "MIT"
    assert doc.compatibility == "Requires Python 3.10+"
    assert doc.allowed_tools == ("Bash", "Read", "Write")


def test_existing_fields_still_work():
    """向后兼容: 现有 8 个 sage 扩展字段仍正常初始化。"""
    doc = SkillMdDocument(
        name="x",
        description="A tool",
        triggers=["x", "xtra"],
        version="1.2.3",
        metadata={"author": "sage"},
    )
    assert doc.triggers == ["x", "xtra"]
    assert doc.version == "1.2.3"
    assert doc.metadata == {"author": "sage"}
```

- [ ] **Step 2: Run tests, expect 4 of 5 to FAIL**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_skillmd_doc.py -v`

Expected:
- 4 tests FAIL (`test_default_license_is_none`, `test_default_compatibility_is_none`, `test_default_allowed_tools_is_empty_tuple`, `test_set_new_fields`)
- `test_existing_fields_still_work` PASSES

- [ ] **Step 3: Add 3 new fields to `SkillMdDocument` dataclass**

Replace `backend/skills/skill_md/skill.py:49-67`:

```python
@dataclass
class SkillMdDocument:
    """一份 SKILL.md 文件解析后的全部内容。"""

    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    base_dir: Path | None = None
    version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)

    # v2 新增字段(向后兼容)
    requires: RequiresSpec = field(default_factory=RequiresSpec)
    os: list[str] = field(default_factory=list)  # 平台过滤
    always: bool = False  # 跳过条件加载
    dispatch: DispatchMode = field(default_factory=DispatchMode)
    resources: Any | None = None  # ResourceIndex,由 loader 构建

    # agentskills.io spec optional fields (Task 3)
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
```

- [ ] **Step 4: Run tests, expect all 5 to PASS**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_skillmd_doc.py -v`

Expected: all 5 tests PASS.

- [ ] **Step 5: Run all skill_md tests, expect zero regression**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/ -v`

Expected: all existing tests still pass.

- [ ] **Step 6: Commit Task 3**

```bash
cd /home/fz/project/sage
git add backend/skills/skill_md/skill.py backend/tests/skills/skill_md/test_skillmd_doc.py
git commit -m "feat(skill-md): add license/compatibility/allowed_tools to SkillMdDocument

Add 3 new dataclass fields for agentskills.io spec optional fields:

- license: str | None
- compatibility: str | None
- allowed_tools: tuple[str, ...] (parsed by loader in Task 4)

All fields have backward-compatible defaults. Existing SkillMdDocument
constructors (without these fields) continue to work.

Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md"
```

---

## Task 4: Loader — name-vs-parent-dir warning + allowed-tools parsing + pass new fields

**Files:**
- Modify: `backend/skills/skill_md/loader.py:131-230` (`_load_from_path`)
- Test: `backend/tests/skills/skill_md/test_loader_compliance.py` (new file)

**Interfaces:**
- Consumes: existing `_load_from_path(path: Path) -> bool` signature
- Produces:
  - `logger.warning` when `meta["name"] != path.parent.name` (does not block)
  - `meta["allowed-tools"]` parsed into `tuple` (split by space, filter empty, preserve order)
  - `SkillMdDocument(...)` constructor receives new 3 fields: `license`, `compatibility`, `allowed_tools`

- [ ] **Step 1: Create test file with 4 failing integration tests**

Create `backend/tests/skills/skill_md/test_loader_compliance.py`:

```python
"""Integration tests for SkillMdHotLoader spec compliance (Task 4 + Task 5)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.loader import SkillMdHotLoader


@pytest.fixture
def tmp_skills_dir(tmp_path: Path) -> Path:
    """返回临时 skills 根目录。"""
    return tmp_path


def test_load_with_license_field(tmp_skills_dir: Path, caplog):
    skill_dir = tmp_skills_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: A tool that does X\n"
        "license: MIT\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    with caplog.at_level(logging.WARNING):
        loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
        loaded, _ = loader.scan_and_load()
    assert loaded == 1
    skill = registry.get("my-skill")
    assert skill._doc.license == "MIT"


def test_load_with_compatibility_field(tmp_skills_dir: Path):
    skill_dir = tmp_skills_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: A tool that does X\n"
        "compatibility: Requires Python 3.10+\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    assert registry.get("my-skill")._doc.compatibility == "Requires Python 3.10+"


def test_load_with_allowed_tools_field(tmp_skills_dir: Path):
    skill_dir = tmp_skills_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: A tool that does X\n"
        "allowed-tools: Bash Read Write\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    assert registry.get("my-skill")._doc.allowed_tools == ("Bash", "Read", "Write")


def test_name_mismatch_with_parent_dir_warns(tmp_skills_dir: Path, caplog):
    """name != parent_dir.name 时 WARNING,不阻断加载。"""
    skill_dir = tmp_skills_dir / "search"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: coder-search\n"
        "description: Use this when searching code\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    with caplog.at_level(logging.WARNING):
        loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
        loaded, _ = loader.scan_and_load()
    assert loaded == 1  # 不阻断
    assert "agentskills.io spec recommends" in caplog.text
    assert "coder-search" in caplog.text
    assert "search" in caplog.text
```

- [ ] **Step 2: Run tests, expect 4 to FAIL**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_loader_compliance.py -v`

Expected: all 4 tests FAIL (loader doesn't pass new fields, doesn't emit warning).

- [ ] **Step 3: Add `allowed-tools` parsing helper + modify `_load_from_path`**

First, add a helper function near the top of `backend/skills/skill_md/loader.py` (after imports around line 35):

```python
def _parse_allowed_tools(tools_str: Any) -> tuple[str, ...]:
    """解析 allowed-tools 字段: 空格分隔字符串 → tuple (去空, 保序)。

    Args:
        tools_str: 来自 frontmatter 的 raw 值(可能为 None / str / 其他)。

    Returns:
        元组,如 ``("Bash", "Read", "Write")``。
        非字符串输入返回空元组(防御性 fallback)。
    """
    if not isinstance(tools_str, str):
        return ()
    return tuple(part for part in tools_str.split() if part)
```

Then replace the `SkillMdDocument(...)` construction in `loader.py:169-195` (inside `_load_from_path`):

```python
        doc = SkillMdDocument(
            name=name,
            description=meta.get("description", ""),
            triggers=list(meta.get("triggers", []))
            if isinstance(meta.get("triggers"), list)
            else [],
            body=body,
            base_dir=path.parent,
            version=str(meta["version"]) if "version" in meta else None,
            metadata=dict(meta.get("metadata", {}))
            if isinstance(meta.get("metadata"), dict)
            else {},
            raw_frontmatter=dict(meta),
            # v2 字段
            requires=requires_spec,
            os=list(meta.get("os", [])) if isinstance(meta.get("os"), list) else [],
            always=bool(meta.get("always", False)),
            dispatch=DispatchMode(
                disable_model_invocation=bool(meta.get("disable-model-invocation", False)),
                user_invocable=bool(meta.get("user-invocable", False)),
                user_invocable_name=str(meta["user-invocable-name"])
                if "user-invocable-name" in meta
                else None,
                command_dispatch=str(meta.get("command-dispatch", "auto")),
            ),
            resources=None,  # ResourceIndex 后续构建
        )
```

With:

```python
        # agentskills.io spec optional fields (Task 4)
        license_val = meta.get("license")
        compatibility_val = meta.get("compatibility")
        allowed_tools_tuple = _parse_allowed_tools(meta.get("allowed-tools"))

        doc = SkillMdDocument(
            name=name,
            description=meta.get("description", ""),
            triggers=list(meta.get("triggers", []))
            if isinstance(meta.get("triggers"), list)
            else [],
            body=body,
            base_dir=path.parent,
            version=str(meta["version"]) if "version" in meta else None,
            metadata=dict(meta.get("metadata", {}))
            if isinstance(meta.get("metadata"), dict)
            else {},
            raw_frontmatter=dict(meta),
            # v2 字段
            requires=requires_spec,
            os=list(meta.get("os", [])) if isinstance(meta.get("os"), list) else [],
            always=bool(meta.get("always", False)),
            dispatch=DispatchMode(
                disable_model_invocation=bool(meta.get("disable-model-invocation", False)),
                user_invocable=bool(meta.get("user-invocable", False)),
                user_invocable_name=str(meta["user-invocable-name"])
                if "user-invocable-name" in meta
                else None,
                command_dispatch=str(meta.get("command-dispatch", "auto")),
            ),
            resources=None,  # ResourceIndex 后续构建
            # agentskills.io spec optional fields (Task 4)
            license=license_val if isinstance(license_val, str) else None,
            compatibility=compatibility_val if isinstance(compatibility_val, str) else None,
            allowed_tools=allowed_tools_tuple,
        )
```

- [ ] **Step 4: Add `name != parent_dir.name` warning after `SkillMdDocument` construction**

In `loader.py`, **after** the `doc = SkillMdDocument(...)` line, **before** the gating check (`if self._gating_ctx is not None:`), add:

```python
        # agentskills.io spec: name 应匹配父目录名 (Task 4)
        # 仅 warning,不阻断加载(避免破坏历史 SKILL.md 的命名习惯)
        parent_name = path.parent.name
        if name != parent_name:
            logger.warning(
                "SKILL.md at %s declares name='%s' but parent dir is '%s'; "
                "agentskills.io spec recommends name matches parent dir",
                path,
                name,
                parent_name,
            )
```

- [ ] **Step 5: Run tests, expect all 4 to PASS**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_loader_compliance.py -v`

Expected: all 4 tests PASS.

- [ ] **Step 6: Run all skill_md tests, expect zero regression**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/ -v`

Expected: all existing tests still pass.

- [ ] **Step 7: Commit Task 4**

```bash
cd /home/fz/project/sage
git add backend/skills/skill_md/loader.py backend/tests/skills/skill_md/test_loader_compliance.py
git commit -m "feat(skill-md): loader parses new spec fields + warns on name-parent mismatch

- Add _parse_allowed_tools helper: space-separated string -> tuple
- Pass license / compatibility / allowed_tools into SkillMdDocument
- Emit WARNING (not block) when frontmatter 'name' != parent dir name
  (agentskills.io spec recommends match; sage legacy uses different
  naming, so warn-only to preserve backward compat)

Existing SKILL.md files (no new fields) continue to load with
license=None, compatibility=None, allowed_tools=() defaults.

Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md
Refs: https://agentskills.io/specification#name-field"
```

---

## Task 5: Loader — support single-file `<dir>/SKILL.md` form

**Files:**
- Modify: `backend/skills/skill_md/loader.py:92-129` (`scan_and_load`)
- Test: `backend/tests/skills/skill_md/test_loader_compliance.py` (append more tests)

**Interfaces:**
- Consumes: existing `scan_and_load() -> tuple[int, int]` signature
- Produces: same return type, but additionally scans for single-file form `<dir>/SKILL.md` after subdirectory form (lower priority)

- [ ] **Step 1: Append 4 more integration tests**

Append the following to `backend/tests/skills/skill_md/test_loader_compliance.py`:

```python
# ---- single-file form (Task 5) ----

def test_load_single_file_form_skill_md(tmp_skills_dir: Path, caplog):
    """<dir>/SKILL.md 单文件形态加载(新能力)。"""
    (tmp_skills_dir / "SKILL.md").write_text(
        "---\n"
        "name: root-skill\n"
        "description: Use this single-file root skill\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    with caplog.at_level(logging.WARNING):
        loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
        loaded, _ = loader.scan_and_load()
    assert loaded == 1
    skill = registry.get("root-skill")
    assert skill is not None
    # 预期内 warning (parent dir != name)
    assert "agentskills.io spec recommends" in caplog.text


def test_single_file_form_lower_priority_than_subdir(tmp_skills_dir: Path):
    """当同名前后冲突,子目录形态优先(builtin 名称 > 子目录 > 单文件)。"""
    sub = tmp_skills_dir / "my-skill"
    sub.mkdir()
    (sub / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Use this subdir form\n---\nbody",
        encoding="utf-8",
    )
    (tmp_skills_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Use this single-file form\n---\nbody",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    # 子目录形态胜(loaded first)
    assert "subdir form" in registry.get("my-skill")._doc.body


def test_existing_skills_still_load_compatible(tmp_skills_dir: Path):
    """现有 SKILL.md 无新字段,继续正常加载(向后兼容)。"""
    skill_dir = tmp_skills_dir / "legacy-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: legacy-skill\n"
        "description: Use this when you need legacy behavior\n"
        "triggers:\n  - legacy\n  - old\n"
        "version: 0.5.0\n"
        "metadata:\n  author: sage\n"
        "---\n"
        "Legacy body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    doc = registry.get("legacy-skill")._doc
    assert doc.license is None
    assert doc.compatibility is None
    assert doc.allowed_tools == ()
    assert doc.triggers == ["legacy", "old"]
    assert doc.version == "0.5.0"
    assert doc.metadata == {"author": "sage"}


def test_no_license_field_loaded_as_none(tmp_skills_dir: Path):
    """无 license 字段 → doc.license is None。"""
    skill_dir = tmp_skills_dir / "no-license"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: no-license\ndescription: A tool without license field\n---\nbody",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    assert registry.get("no-license")._doc.license is None
```

- [ ] **Step 2: Run tests, expect 2 single-file tests to FAIL**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_loader_compliance.py -v -k "single_file or no_license or existing_skills"`

Expected:
- `test_load_single_file_form_skill_md` FAILS
- `test_single_file_form_lower_priority_than_subdir` FAILS
- `test_existing_skills_still_load_compatible` PASSES
- `test_no_license_field_loaded_as_none` PASSES (Task 4 already made this work)

- [ ] **Step 3: Modify `scan_and_load` to support single-file form**

Replace `backend/skills/skill_md/loader.py:92-129` (`scan_and_load`):

```python
    def scan_and_load(self) -> tuple[int, int]:
        """扫描所有 dirs, 加载新 SKILL.md。返回 ``(loaded_count, skipped_count)``。

        支持两种文件形态 (agentskills.io spec):
          - 形态 A: 子目录形态 <dir>/<name>/SKILL.md (v1 已有)
          - 形态 B: 单文件形态 <dir>/SKILL.md (Task 5 新增)

        skipped_count 包括:
          - builtin 同名冲突
          - parse 失败
          - 验证失败 (缺 name/description, name 不是 slug)
          - 实例化失败 (极少见, 但防御性兜底)

        优先级: builtin 名称 > 子目录形态 > 单文件形态(同 name 时后者 skip)。
        """
        loaded = 0
        skipped = 0
        for d in self._dirs:
            if not d.is_dir():
                continue
            # 形态 A: 子目录形态 <dir>/<name>/SKILL.md
            for entry in sorted(d.iterdir()):
                if not entry.is_dir():
                    continue
                if entry.name.startswith("."):
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    continue
                try:
                    if self._load_from_path(skill_md):
                        loaded += 1
                    else:
                        skipped += 1
                except Exception as exc:  # noqa: BLE001 - 防御性兜底
                    logger.warning(
                        "SKILL.md load failed for %s: %s",
                        skill_md,
                        sanitize_for_logging(str(exc), max_len=200),
                    )
                    skipped += 1
            # 形态 B: 单文件形态 <dir>/SKILL.md (Task 5)
            root_skill_md = d / "SKILL.md"
            if root_skill_md.is_file():
                try:
                    if self._load_from_path(root_skill_md):
                        loaded += 1
                    else:
                        skipped += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "SKILL.md single-file load failed for %s: %s",
                        root_skill_md,
                        sanitize_for_logging(str(exc), max_len=200),
                    )
                    skipped += 1
        if loaded:
            logger.info("SkillMd scan: %d loaded, %d skipped", loaded, skipped)
        return loaded, skipped
```

- [ ] **Step 4: Run all 8 loader tests, expect all to PASS**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/test_loader_compliance.py -v`

Expected: all 8 tests PASS (4 from Task 4 + 4 from Task 5).

- [ ] **Step 5: Run all skill_md tests, expect zero regression**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/skills/skill_md/ -v`

Expected: all existing tests still pass.

- [ ] **Step 6: Commit Task 5**

```bash
cd /home/fz/project/sage
git add backend/skills/skill_md/loader.py backend/tests/skills/skill_md/test_loader_compliance.py
git commit -m "feat(skill-md): loader supports single-file <dir>/SKILL.md form

agentskills.io spec allows both directory form (<dir>/<name>/SKILL.md)
and single-file form (<dir>/SKILL.md where name comes from frontmatter).

Add support for single-file form in SkillMdHotLoader.scan_and_load:
- After scanning subdirectory form, additionally scan for <dir>/SKILL.md
- Priority: builtin > subdirectory form > single-file form
  (later scan with same name is skipped via registry.exists check)
- Single-file form triggers expected name-vs-parent-dir warning
  (parent dir name != frontmatter name)

Backward compatible: all existing directory-form skills still load
identically (subdirectory form is scanned first).

Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md
Refs: https://agentskills.io/specification#directory-structure"
```

---

## Task 6: E2E smoke test — full skill loads in chat

**Files:**
- Create: `tests/electron/skillmd-compliance.spec.ts` (new file)

**Interfaces:**
- Consumes: existing Playwright Electron test patterns from `tests/electron/smoke.spec.ts`
- Produces: 1 E2E test that places a spec-compliant SKILL.md in a temp directory, launches the app via Electron, and verifies the skill registers in the chat input

- [ ] **Step 1: Read existing smoke test for pattern reference**

Run: `head -50 /home/fz/project/sage/tests/electron/smoke.spec.ts`

Verify the test file uses Playwright's `_electron` launch pattern. Note the import statement and `test()` structure to mirror.

- [ ] **Step 2: Create E2E test file**

Create `tests/electron/skillmd-compliance.spec.ts`:

```typescript
/**
 * E2E smoke test: SKILL.md spec compliance end-to-end.
 *
 * Verifies that a SKILL.md file conforming to agentskills.io spec
 * (with new license/compatibility/allowed-tools fields) loads correctly
 * in the running sage app and registers in the chat skill autocomplete.
 */

import { test, expect, _electron as electron, ElectronApplication, Page } from '@playwright/test';
import * as path from 'path';
import * as os from 'os';
import * as fs from 'fs';

const REPO_ROOT = path.resolve(__dirname, '..', '..');

test.describe('SKILL.md spec compliance (agentskills.io)', () => {
  let app: ElectronApplication;
  let page: Page;
  let tempSkillDir: string;

  test.beforeAll(async () => {
    // Create a temporary skills directory with a spec-compliant SKILL.md
    tempSkillDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sage-skills-test-'));
    const skillDir = path.join(tempSkillDir, 'spec-compliant-skill');
    fs.mkdirSync(skillDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillDir, 'SKILL.md'),
      `---
name: spec-compliant-skill
description: Use this when verifying agentskills.io spec compliance
license: MIT
compatibility: Requires Python 3.10+
allowed-tools: Bash Read
---
# Spec Compliant Skill

This skill is used for E2E testing of agentskills.io spec conformance.
`,
      'utf-8',
    );

    // Launch Electron app with SAGE_SKILLS_DIR pointing to our temp dir
    app = await electron.launch({
      args: [path.join(REPO_ROOT, 'dist-electron', 'main.js')],
      env: {
        ...process.env,
        SAGE_SKILLS_DIR: tempSkillDir,
      },
    });
    page = await app.firstWindow();
    await page.waitForLoadState('load', { timeout: 30000 });
  });

  test.afterAll(async () => {
    if (app) await app.close();
    if (tempSkillDir) fs.rmSync(tempSkillDir, { recursive: true, force: true });
  });

  test('spec-compliant skill loads and registers in chat', async () => {
    // Open chat input
    const chatInput = page.getByRole('textbox', { name: /chat|message/i }).first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    // Type the skill trigger
    await chatInput.fill('/spec-compliant-skill');

    // Verify the skill is suggested in autocomplete
    const suggestion = page.getByText(/spec-compliant-skill/i).first();
    await expect(suggestion).toBeVisible({ timeout: 5000 });
  });
});
```

- [ ] **Step 3: Verify test file syntax**

Run: `cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npx tsc --noEmit tests/electron/skillmd-compliance.spec.ts`

Expected: no TypeScript errors.

- [ ] **Step 4: Run E2E test**

Run: `cd /home/fz/project/sage && /home/fz/.nvm/versions/node/v25.9.0/bin/npm run test:e2e -- skillmd-compliance --reporter=line`

Expected: 1 test passes (test may take 30-60s due to Electron launch).

Note: This E2E test requires a built Electron app. If the build is not present, run `npm run electron:build` first.

- [ ] **Step 5: Commit Task 6**

```bash
cd /home/fz/project/sage
git add tests/electron/skillmd-compliance.spec.ts
git commit -m "test(e2e): add SKILL.md spec compliance smoke test

Add E2E test verifying that a spec-compliant SKILL.md (with new
license / compatibility / allowed-tools fields) loads correctly
in the Electron app and registers in the chat autocomplete.

Uses SAGE_SKILLS_DIR env var to point loader at a temp directory
containing a single spec-compliant skill.

Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md"
```

---

## Task 7: Documentation + CHANGELOG

**Files:**
- Create: `docs/technical/31-skill-md-spec-conformance.md` (new technical doc)
- Modify: `docs/technical/07-skills.md` (append "Spec Conformance" subsection)
- Modify: `CHANGELOG.md` (add Unreleased entry)

**Interfaces:**
- Consumes: existing docs/technical/ section numbering
- Produces: 1 new technical doc + 1 incremental update to existing skills doc + 1 CHANGELOG entry

- [ ] **Step 1: Read existing technical doc numbering**

Run: `ls /home/fz/project/sage/docs/technical/ | sort`

Find the highest existing number. As of 2026-06-29, use **31** (next sequential).

- [ ] **Step 2: Create new technical doc**

Create `docs/technical/31-skill-md-spec-conformance.md`:

```markdown
# 31. SKILL.md Spec Conformance (agentskills.io)

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

## Future Work (Not in This Spec)

- Wire `allowed-tools` into a tool gateway layer for permission pre-flight checks
- Add `sage skills lint` CLI to validate SKILL.md against the spec
- Author tutorial in `docs/user-manual/` for "Writing Your First SKILL.md"

## Related Documents

- `docs/technical/07-skills.md` — original skills architecture (now appends "Spec Conformance" subsection)
- `docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md` — design spec
- `docs/superpowers/plans/2026-06-29-agentskills-io-spec-conformance.md` — implementation plan
```

- [ ] **Step 3: Append "Spec Conformance" subsection to `docs/technical/07-skills.md`**

Read the end of `docs/technical/07-skills.md` (last 20 lines) to find a good insertion point.

Append a new section after the existing "SKILL.md 适配层" section:

```markdown

## SKILL.md Spec Conformance (agentskills.io)

The SKILL.md adapter layer (`backend/skills/skill_md/`) conforms to the [agentskills.io open specification](https://agentskills.io/specification) since 2026-06-29. See `docs/technical/31-skill-md-spec-conformance.md` for full details, including:

- 3 new spec-optional fields (`license`, `compatibility`, `allowed-tools`)
- Strengthened `name` (≤64 chars) and `description` (≤1024 chars) validation
- Single-file `<dir>/SKILL.md` form support
- `name`-vs-parent-dir warning (soft constraint, not blocking)

All changes are forward-compatible: existing SKILL.md files continue to load without modification.
```

- [ ] **Step 4: Add CHANGELOG entry**

Read the top of `/home/fz/project/sage/CHANGELOG.md` (first 30 lines) to find the `## [Unreleased]` section.

Insert under `## [Unreleased]` → `### Added` (create the subsection if absent):

```markdown
### Added
- feat(skills): conform `backend/skills/skill_md/` to agentskills.io spec
  - Add optional fields: `license`, `compatibility` (≤500 chars), `allowed-tools`
  - Strengthen `name` (≤64 chars) and `description` (≤1024 chars) validation
  - Support single-file `<dir>/SKILL.md` form in loader
  - Warn (not block) when frontmatter `name` != parent directory name
  - Emit warning when description lacks trigger keywords
  - All changes forward-compatible; existing SKILL.md files unaffected
  - Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md
```

- [ ] **Step 5: Run full test suite one more time, expect all green**

Run:
```bash
cd /home/fz/project/sage && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
    backend/tests/skills/skill_md/ -v --cov=backend/skills/skill_md
```

Expected: 14 + 5 + 8 = 27 new tests + 80+ existing tests pass. Coverage of `frontmatter.py` ≥ 95%, `skill.py` new fields = 100%, `loader.py` new code ≥ 85%.

- [ ] **Step 6: Commit Task 7**

```bash
cd /home/fz/project/sage
git add docs/technical/31-skill-md-spec-conformance.md \
        docs/technical/07-skills.md \
        CHANGELOG.md
git commit -m "docs(skills): document agentskills.io spec conformance

- Add docs/technical/31-skill-md-spec-conformance.md with full
  spec alignment details, new fields reference, migration notes
- Append 'SKILL.md Spec Conformance' subsection to 07-skills.md
- Add Unreleased entry to CHANGELOG.md under '### Added'

Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md"
```

---

## Self-Review Checklist (Pre-Handoff)

| Item | Status |
|---|---|
| Spec coverage — name length | Task 1 ✓ |
| Spec coverage — description length | Task 1 ✓ |
| Spec coverage — trigger keyword | Task 1 ✓ |
| Spec coverage — license field | Task 2 + 3 + 4 ✓ |
| Spec coverage — compatibility field | Task 2 + 3 + 4 ✓ |
| Spec coverage — allowed-tools field | Task 2 + 3 + 4 ✓ |
| Spec coverage — name matches parent dir | Task 4 ✓ |
| Spec coverage — single-file form | Task 5 ✓ |
| Spec coverage — scripts/references/assets | (already implemented) ✓ |
| Spec coverage — metadata field | (already implemented) ✓ |
| E2E smoke test | Task 6 ✓ |
| Documentation | Task 7 ✓ |
| Placeholder scan (TBD/TODO/"implement later") | none ✓ |
| Type consistency (license / compatibility / allowed_tools naming) | consistent across Task 2/3/4 ✓ |
| Backward compatibility | All Task steps verify zero regression ✓ |
| No new dependencies | pyyaml==6.0.1 unchanged ✓ |

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-29-agentskills-io-spec-conformance.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints