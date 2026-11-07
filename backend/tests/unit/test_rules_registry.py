"""四层规则聚合的单元测试（M3，2026-11-07）。"""

from __future__ import annotations

import pytest

from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_repo import ProjectRepository
from backend.services.rules_registry import (
    ConstraintAdapter,
    RuleEntry,
    RulesRegistry,
    detect_conflicts,
    split_markdown_sections,
)


@pytest.fixture()
def project(tmp_path, setup_test_db):
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    return ProjectRepository().register(str(project_dir))


class _BoomAdapter:
    layer = "constraint"

    def read(self, project):
        raise RuntimeError("adapter exploded")


def test_constraint_adapter_maps_user_constraint(project):
    constraint = ProjectConstraintRepository().create(
        project_id=project.id,
        category="coding_style",
        content="使用双引号字符串",
        priority=7,
        trigger_pattern="*.py",
    )

    entries = ConstraintAdapter().read(project)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == f"constraint:{constraint.id}"
    assert entry.layer == "constraint"
    assert entry.source_label == "项目规则"
    assert entry.editable == "full"
    assert entry.priority == 7
    assert entry.trigger == "*.py"
    assert entry.enabled is True


def test_playbook_projected_constraint_is_readonly(project):
    ProjectConstraintRepository().create(
        project_id=project.id,
        category="artifact",
        content="需求文档必须包含验收标准",
        source="playbook:requirements",
    )

    entry = ConstraintAdapter().read(project)[0]

    assert entry.editable == "readonly"
    assert entry.source_label == "规程 · requirements"
    assert entry.origin == "playbook:requirements"


def test_split_markdown_sections_keeps_preamble_and_headings():
    content = "前言一段\n\n# 输出\n\n用中文。\n\n## 代码\n\n用 ruff。\n"

    sections = split_markdown_sections(content)

    assert [s.heading for s in sections] == ["", "输出", "代码"]
    assert "用中文。" in sections[1].body
    assert sections[2].level == 2


def test_detect_conflicts_flags_same_category_different_content():
    entries = [
        RuleEntry(id="constraint:1", layer="constraint", source_label="项目规则",
                  scope="全局", category="coding_style", content="使用 ruff", priority=5),
        RuleEntry(id="doc:SAGE.md#1", layer="doc", source_label="项目总纲 SAGE.md",
                  scope="/p/SAGE.md", category="coding_style", content="使用 black",
                  editable="readonly"),
        RuleEntry(id="constraint:2", layer="constraint", source_label="项目规则",
                  scope="全局", category="coding_style", content=" 使用 RUFF ", priority=4),
    ]

    conflicts = detect_conflicts(entries)

    assert len(conflicts) == 2
    assert {conflicts[0]["a"], conflicts[0]["b"]} == {"constraint:1", "doc:SAGE.md#1"}
    assert all(c["category"] == "coding_style" for c in conflicts)


def test_detect_conflicts_skips_disjoint_triggers_and_disabled_rows():
    entries = [
        RuleEntry(id="a", layer="constraint", source_label="x", scope="全局",
                  category="format", content="A", trigger="*.py"),
        RuleEntry(id="b", layer="constraint", source_label="x", scope="全局",
                  category="format", content="B", trigger="*.md"),
        RuleEntry(id="c", layer="constraint", source_label="x", scope="全局",
                  category="format", content="C", trigger="*.py", enabled=False),
    ]

    assert detect_conflicts(entries) == []


def test_registry_keeps_reading_when_one_adapter_raises(project):
    registry = RulesRegistry(adapters=[_BoomAdapter(), ConstraintAdapter()])

    entries = registry.list_rules(project)

    assert entries == []
