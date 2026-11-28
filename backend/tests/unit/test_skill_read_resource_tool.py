"""skill_read_resource 工具（spec §4.2）。

只读能力：按 skill 名 + 技能内相对路径读取 references/ 等白名单资源。
路径越界 / 非白名单目录 / 非索引文件一律拒绝并给出明确错误。
"""

import pytest

from backend.skills.skill_md.loader import discover_skill_md_dirs
from backend.tools.skill_resource_tool import (
    SkillReadResourceTool,
    resolve_skill_dir,
)

pytestmark = pytest.mark.unit

SHIPPED_LITERATURE = "literature-research"
PIPELINE_REL = "references/pipeline.md"


def _tool() -> SkillReadResourceTool:
    return SkillReadResourceTool()


def test_shipped_skill_directory_is_resolvable() -> None:
    base = resolve_skill_dir(SHIPPED_LITERATURE)
    assert base is not None, "shipped literature-research 应可解析"
    assert (base / "SKILL.md").is_file()
    assert (base / PIPELINE_REL).is_file()


def test_read_pipeline_reference_returns_content() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path=PIPELINE_REL)
    assert result.success is True, result.error
    assert result.content["path"] == PIPELINE_REL
    assert result.content["total_lines"] > 0
    assert result.content["content"].strip()


def test_offset_and_limit_paginate() -> None:
    result = _tool().execute(
        skill=SHIPPED_LITERATURE, path=PIPELINE_REL, offset=2, limit=3
    )
    assert result.success is True, result.error
    lines = result.content["content"].splitlines()
    assert len(lines) == 3
    assert result.content["offset"] == 2
    assert result.content["truncated"] is True


def test_absolute_path_is_rejected() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path="/etc/passwd")
    assert result.success is False
    assert "path" in (result.error or "").lower()


def test_parent_traversal_is_rejected() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path="references/../../escape.md")
    assert result.success is False


def test_non_whitelisted_directory_is_rejected() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path="SKILL.md")
    assert result.success is False


def test_unknown_skill_is_reported() -> None:
    result = _tool().execute(skill="no-such-skill-xyz", path=PIPELINE_REL)
    assert result.success is False
    assert "no-such-skill-xyz" in (result.error or "")


def test_resolution_order_matches_loader_discovery() -> None:
    """解析顺序必须与技能加载同源：用户层优先于 shipped。"""
    roots = discover_skill_md_dirs()
    base = resolve_skill_dir(SHIPPED_LITERATURE)
    assert base is not None
    if roots:
        expected_first = roots[0] / SHIPPED_LITERATURE
        if expected_first.is_dir() and (expected_first / "SKILL.md").is_file():
            assert base == expected_first.resolve()


def test_auto_activation_manifest_lists_pipeline_reference() -> None:
    from backend.skills.skill_md.auto_activation import render_resource_manifest
    from backend.skills.skill_md.resources import build_resource_index

    base = resolve_skill_dir(SHIPPED_LITERATURE)
    assert base is not None
    manifest = render_resource_manifest(base, build_resource_index(base))
    joined = "\n".join(manifest)
    assert "references/pipeline.md" in joined
    assert "skill_read_resource" in joined


def test_skill_md_declares_the_run_directory_contract() -> None:
    """SKILL.md 必须写出「用 skill_read_resource 读 pipeline.md」的契约。"""
    base = resolve_skill_dir(SHIPPED_LITERATURE)
    assert base is not None
    text = (base / "SKILL.md").read_text(encoding="utf-8")
    assert "skill_read_resource" in text
    assert "references/pipeline.md" in text
