# mypy: disable-error-code="no-untyped-def,attr-defined,func-returns-value"
"""SKILL.md frontmatter 解析器单测。

覆盖 backend.skills.skill_md.frontmatter:
- parse(text) -> (dict, body)
- parse_file(path) -> (dict, body)
- dump(meta, body) -> str
- SkillMdParseError
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.skill_md.frontmatter import (
    SkillMdParseError,
    dump,
    parse,
    parse_file,
)

pytestmark = pytest.mark.unit


# =====================================================================
# parse(text) happy path
# =====================================================================


def test_parse_valid_required_only():
    """只含必填字段 name + description。"""
    text = (
        "---\n"
        "name: hello\n"
        "description: A hello-world skill\n"
        "---\n"
        "\n"
        "Body line 1\n"
        "Body line 2\n"
    )
    meta, body = parse(text)
    assert meta == {"name": "hello", "description": "A hello-world skill"}
    assert body == "Body line 1\nBody line 2\n"


def test_parse_valid_all_optional_fields():
    """AgentSkills 常用可选字段全在。"""
    text = (
        "---\n"
        "name: code-review\n"
        "description: Review a diff\n"
        "version: 0.2.0\n"
        "platforms: [linux, darwin]\n"
        "triggers: [review, code review]\n"
        "metadata:\n"
        "  hermes:\n"
        "    tags: [python, automation]\n"
        "---\n"
        "Body content\n"
    )
    meta, body = parse(text)
    assert meta["name"] == "code-review"
    assert meta["version"] == "0.2.0"
    assert meta["platforms"] == ["linux", "darwin"]
    assert meta["triggers"] == ["review", "code review"]
    assert meta["metadata"] == {"hermes": {"tags": ["python", "automation"]}}
    assert body == "Body content\n"


def test_parse_empty_body():
    """frontmatter 存在但 body 为空。"""
    text = "---\nname: x\ndescription: y\n---\n"
    meta, body = parse(text)
    assert meta == {"name": "x", "description": "y"}
    assert body == ""


def test_parse_missing_frontmatter():
    """无 frontmatter 时整体作为 body 返回,meta 为空 dict。"""
    text = "Just plain markdown\nwithout fence\n"
    meta, body = parse(text)
    assert meta == {}
    assert body == text


def test_parse_preserves_unclosed_fence_in_body():
    """body 内含 `---` 子串时不应误切分。"""
    text = (
        "---\n"
        "name: x\n"
        "description: y\n"
        "---\n"
        "intro\n"
        "---\n"  # 内层分隔符,只是普通 markdown
        "after\n"
    )
    meta, body = parse(text)
    assert meta == {"name": "x", "description": "y"}
    assert body == "intro\n---\nafter\n"


# =====================================================================
# parse(text) error path
# =====================================================================


def test_parse_unclosed_fence_raises():
    """开始 fence 后没有闭合 → SkillMdParseError。"""
    text = "---\nname: x\ndescription: y\nNo close\n"
    with pytest.raises(SkillMdParseError):
        parse(text)


def test_parse_malformed_yaml_raises():
    """YAML 语法错 → SkillMdParseError(包装 yaml.YAMLError)。"""
    text = (
        "---\n"
        "name: x\n"
        "description: y\n"
        "bad: [unclosed\n"  # 列表未闭合
        "---\n"
        "body\n"
    )
    with pytest.raises(SkillMdParseError):
        parse(text)


def test_parse_missing_name_raises():
    text = "---\n" "description: y\n" "---\n" "body\n"
    with pytest.raises(SkillMdParseError) as exc:
        parse(text)
    assert "name" in str(exc.value).lower()


def test_parse_missing_description_raises():
    text = "---\n" "name: x\n" "---\n" "body\n"
    with pytest.raises(SkillMdParseError) as exc:
        parse(text)
    assert "description" in str(exc.value).lower()


def test_parse_invalid_name_slug_raises():
    """name 不是合法 slug(大写/空格/中文) → SkillMdParseError。"""
    text = "---\nname: Has Spaces\ndescription: y\n---\nbody\n"
    with pytest.raises(SkillMdParseError):
        parse(text)


# =====================================================================
# line endings & BOM
# =====================================================================


def test_parse_crlf_line_endings():
    text = "---\r\n" "name: x\r\n" "description: y\r\n" "---\r\n" "body\r\n"
    meta, body = parse(text)
    assert meta == {"name": "x", "description": "y"}
    assert body == "body\r\n"


def test_parse_utf8_bom():
    """UTF-8 BOM 在最前面应被剥除。"""
    text = "﻿---\nname: x\ndescription: y\n---\nbody\n"
    meta, body = parse(text)
    assert meta == {"name": "x", "description": "y"}
    assert body == "body\n"


def test_parse_frontmatter_not_a_dict_raises():
    """frontmatter 是 YAML list 而非 dict → SkillMdParseError。"""
    text = "---\n- one\n- two\n---\nbody\n"
    with pytest.raises(SkillMdParseError):
        parse(text)


# =====================================================================
# dump / round-trip
# =====================================================================


def test_dump_roundtrip():
    """dump → parse 应回等。"""
    meta = {"name": "x", "description": "y"}
    body = "Body\nLine2\n"
    text = dump(meta, body)
    meta2, body2 = parse(text)
    assert meta2 == meta
    assert body2 == body


# =====================================================================
# parse_file
# =====================================================================


def test_parse_file_reads_path(tmp_path: Path):
    p = tmp_path / "SKILL.md"
    p.write_text(
        "---\nname: file\ndescription: from file\n---\nfile body\n",
        encoding="utf-8",
    )
    meta, body = parse_file(p)
    assert meta == {"name": "file", "description": "from file"}
    assert body == "file body\n"


def test_parse_file_missing_raises(tmp_path: Path):
    p = tmp_path / "missing.md"
    with pytest.raises(SkillMdParseError):
        parse_file(p)
