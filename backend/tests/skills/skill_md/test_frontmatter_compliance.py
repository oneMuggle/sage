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
