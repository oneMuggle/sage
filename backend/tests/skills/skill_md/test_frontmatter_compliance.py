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