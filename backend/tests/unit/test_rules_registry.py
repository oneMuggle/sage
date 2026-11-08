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


from backend.data.playbook_repo import PlaybookRepository
from backend.services.rules_registry import (
    GlobalRulesAdapter,
    PlaybookAdapter,
    ProjectDocAdapter,
)


def _bind_playbook(project, spec):
    PlaybookRepository().create_snapshot(project.id, spec, source="custom")


def test_playbook_adapter_reads_stage_rules_and_content_checks(project):
    _bind_playbook(
        project,
        {
            "schema_version": "1.0",
            "id": "demo",
            "name": "Demo",
            "stages": [
                {
                    "id": "requirements",
                    "label": "需求分析",
                    "order": 1,
                    "objective": "澄清需求",
                    "rules": [{"text": "需求必须可验收"}],
                    "artifacts": [
                        {
                            "id": "req_doc",
                            "label": "需求文档",
                            "required": True,
                            "match": {"globs": ["requirements*.md"]},
                            "content_checks": [
                                {
                                    "id": "has_acceptance",
                                    "label": "包含验收标准",
                                    "type": "keyword",
                                    "keywords": ["验收", "标准"],
                                }
                            ],
                        }
                    ],
                    "exit_criteria": [],
                }
            ],
            "global_rules": [],
        },
    )

    entries = PlaybookAdapter().read(project)

    assert [entry.id for entry in entries] == [
        "playbook:requirements:0",
        "playbook:requirements:check:req_doc:has_acceptance",
    ]
    assert entries[0].source_label == "规程 · 需求分析"
    assert all(entry.editable == "partial" for entry in entries)
    assert "验收标准" in entries[1].content


def test_playbook_adapter_returns_empty_without_active_snapshot(project):
    assert PlaybookAdapter().read(project) == []


def test_global_rules_adapter_splits_sections(tmp_path, monkeypatch, project):
    monkeypatch.setenv("HOME", str(tmp_path))
    sage_dir = tmp_path / ".sage"
    sage_dir.mkdir()
    (sage_dir / "SAGE.md").write_text("# 输出\n\n用中文。\n\n# 风格\n\n简洁。\n", encoding="utf-8")

    entries = GlobalRulesAdapter().read(project)

    assert [entry.id for entry in entries] == ["global:#0", "global:#1"]
    assert [entry.category for entry in entries] == ["输出", "风格"]
    assert entries[0].source_label == "全局规则"
    assert entries[0].editable == "full"


def test_project_doc_adapter_marks_only_root_sage_writable(tmp_path, setup_test_db):
    parent = tmp_path / "workspace"
    parent.mkdir()
    (parent / "AGENTS.md").write_text("# 祖先规则\n\n不要提交密钥。\n", encoding="utf-8")
    root = parent / "demo"
    root.mkdir()
    (root / "SAGE.md").write_text("# 项目规则\n\n跑 pytest。\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# 工具说明\n\n用 conda。\n", encoding="utf-8")
    project = ProjectRepository().register(str(root))

    entries = ProjectDocAdapter().read(project)

    by_name = {entry.id.split("#")[0]: entry for entry in entries}
    assert by_name["doc:SAGE.md"].editable == "full"
    assert by_name["doc:CLAUDE.md"].editable == "readonly"
    assert by_name["doc:AGENTS.md"].editable == "readonly"
    # 祖先目录在前，即注入顺序
    assert [entry.id.split("#")[0] for entry in entries] == [
        "doc:AGENTS.md",
        "doc:SAGE.md",
        "doc:CLAUDE.md",
    ]


def test_registry_effective_orders_layers_and_reports_conflicts(project, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".sage").mkdir()
    (tmp_path / ".sage" / "SAGE.md").write_text("# 风格\n\n用 black。\n", encoding="utf-8")
    ProjectConstraintRepository().create(
        project_id=project.id, category="风格", content="用 ruff"
    )

    payload = RulesRegistry().effective(project)

    assert [entry["layer"] for entry in payload["entries"]] == ["global", "constraint"]
    assert len(payload["conflicts"]) == 1


def test_effective_excludes_disabled_rules(project):
    ProjectConstraintRepository().create(
        project_id=project.id, category="风格", content="用 ruff"
    )
    disabled = ProjectConstraintRepository().create(
        project_id=project.id, category="风格", content="用 black"
    )
    ProjectConstraintRepository().update(disabled.id, enabled=False)

    payload = RulesRegistry(adapters=[ConstraintAdapter()]).effective(project)

    assert [entry["content"] for entry in payload["entries"]] == ["用 ruff"]
    assert payload["conflicts"] == []
