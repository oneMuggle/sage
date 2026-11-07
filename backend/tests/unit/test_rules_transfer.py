"""规则包传输层单测（M6，2026-11-07）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.services.rules_transfer import (
    MAX_EXPORT_FILE_BYTES,
    SAGE_RULES_FORMAT,
    SAGE_RULES_VERSION,
    RulesImportValidationError,
    build_rules_export_envelope,
    diff_rules_import,
    parse_rules_import,
    render_rules_agents_md,
    render_rules_markdown,
)


@dataclass
class _FakeProject:
    id: str
    name: str
    path: str
    project_type: str = "coding"


@dataclass
class _FakeEntry:
    id: str
    layer: str
    source_label: str
    scope: str
    category: str
    content: str
    enabled: bool = True
    editable: str = "full"
    priority: int = 5
    trigger: str | None = None
    updated_at: int | None = None
    origin: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "layer": self.layer,
            "source_label": self.source_label,
            "scope": self.scope,
            "category": self.category,
            "content": self.content,
            "enabled": self.enabled,
            "editable": self.editable,
            "priority": self.priority,
            "trigger": self.trigger,
            "updated_at": self.updated_at,
            "origin": self.origin,
        }


def test_format_and_version_constants():
    assert SAGE_RULES_FORMAT == "sage.rules"
    assert SAGE_RULES_VERSION == 1
    assert MAX_EXPORT_FILE_BYTES == 1_048_576


def test_build_envelope_includes_user_constraints_only():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    entries = [
        _FakeEntry(
            id="constraint:u1",
            layer="constraint",
            source_label="项目规则",
            scope="全局",
            category="coding_style",
            content="统一使用 ruff",
            editable="full",
        ),
        _FakeEntry(
            id="constraint:p1",
            layer="constraint",
            source_label="规程 · 需求分析",
            scope="需求分析",
            category="交付物",
            content="提交 PR 前补测试",
            editable="readonly",
            origin="playbook:requirements",
        ),
    ]

    envelope = build_rules_export_envelope(project, entries)

    assert envelope["format"] == SAGE_RULES_FORMAT
    assert envelope["version"] == SAGE_RULES_VERSION
    assert envelope["project"] == {"name": "sage", "type": "coding"}
    assert "constraints" in envelope["layers"]
    categories = [item["category"] for item in envelope["layers"]["constraints"]]
    assert "coding_style" in categories
    # 规程投影不应被导出 —— 它属于规程包，规则包不重复打包
    origins = [item.get("origin") for item in envelope["layers"]["constraints"]]
    assert "playbook:requirements" not in origins

    # 导出范围开关：取消勾选「项目规则」时该层必须为空
    trimmed = build_rules_export_envelope(project, entries, include_constraints=False)
    assert trimmed["layers"]["constraints"] == []


def test_build_envelope_includes_docs_when_requested(tmp_path: Path):
    project = _FakeProject(id="p1", name="sage", path=str(tmp_path))
    (tmp_path / "SAGE.md").write_text("# 项目规则\n\n跑 pytest。\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# 工具\n\n用 conda。\n", encoding="utf-8")
    entries = [
        _FakeEntry(
            id="doc:SAGE.md#0",
            layer="doc",
            source_label="SAGE.md",
            scope="SAGE.md",
            category="项目规则",
            content="跑 pytest。",
            editable="full",
        ),
        _FakeEntry(
            id="doc:CLAUDE.md#0",
            layer="doc",
            source_label="CLAUDE.md",
            scope="CLAUDE.md",
            category="工具",
            content="用 conda。",
            editable="readonly",
        ),
    ]

    envelope = build_rules_export_envelope(project, entries, include_docs=True)

    docs = envelope["layers"]["project_docs"]
    assert "SAGE.md" in docs
    assert "CLAUDE.md" in docs
    assert "跑 pytest。" in docs["SAGE.md"]


def test_build_envelope_omits_global_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    (home / ".sage").mkdir()
    (home / ".sage" / "SAGE.md").write_text("# 全局\n\n偏好。\n", encoding="utf-8")
    project = _FakeProject(id="p1", name="sage", path=str(tmp_path))

    envelope = build_rules_export_envelope(project, [])

    assert envelope["layers"]["global_rules"] == ""


def test_build_envelope_includes_global_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    (home / ".sage").mkdir()
    (home / ".sage" / "SAGE.md").write_text("# 全局\n\n偏好。\n", encoding="utf-8")
    project = _FakeProject(id="p1", name="sage", path=str(tmp_path))

    envelope = build_rules_export_envelope(project, [], include_global=True)

    assert "偏好。" in envelope["layers"]["global_rules"]


def test_build_envelope_attaches_playbook_envelope_when_requested():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    # normalize_playbook 要求合法的 schema major 与非空 stages —— 用最小合法 spec
    spec = {
        "id": "pb-1",
        "name": "Demo",
        "schema_version": "1.0",
        "applies_to": {"project_types": ["coding"], "sub_types": []},
        "stages": [{"id": "s1", "label": "阶段一"}],
        "directory_layout": [],
    }

    envelope = build_rules_export_envelope(
        project, [], include_playbook=True, playbook_spec=spec
    )

    assert envelope["layers"]["playbook"]["format"] == "sage.playbook"
    assert envelope["layers"]["playbook"]["playbook"]["id"] == "pb-1"


def test_render_rules_markdown_groups_layers():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    entries = [
        _FakeEntry(
            id="c:1",
            layer="constraint",
            source_label="项目规则",
            scope="全局",
            category="风格",
            content="统一使用 ruff",
        ),
    ]
    md = render_rules_markdown(
        project,
        entries,
        global_rules_text="# 全局\n\n全局偏好。\n",
        playbook_markdown="# 规程\n\n阶段 A。\n",
    )

    assert "# 项目规则" in md or "##" in md
    assert "ruff" in md
    assert "全局偏好" in md
    assert "阶段 A" in md


def test_render_rules_agents_md_emits_plain_rules():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    entries = [
        _FakeEntry(
            id="c:1",
            layer="constraint",
            source_label="项目规则",
            scope="全局",
            category="风格",
            content="统一使用 ruff",
        ),
        _FakeEntry(
            id="c:2",
            layer="constraint",
            source_label="项目规则",
            scope="全局",
            category="提交",
            content="一行一个 commit",
        ),
    ]

    out = render_rules_agents_md(project, entries, global_rules_text="# 全局\n\n偏好。\n")

    assert "ruff" in out
    assert "commit" in out
    # AGENTS.md 风格：不保留 JSON 信封，只留可读规则
    assert "format" not in out
    assert '"id"' not in out


def test_parse_rejects_wrong_format():
    with pytest.raises(RulesImportValidationError) as exc:
        parse_rules_import({"format": "sage.playbook", "version": 1, "layers": {}})

    assert exc.value.status_code == 400
    assert exc.value.format == "sage.rules"


def test_parse_rejects_unknown_version():
    with pytest.raises(RulesImportValidationError) as exc:
        parse_rules_import({"format": "sage.rules", "version": 99, "layers": {}})

    assert exc.value.status_code == 400


def test_parse_rejects_oversize_payload():
    # 必须构造真实超限内容：json 空白填充会在解析时被丢弃，不能用作超限样本
    payload = {
        "format": "sage.rules",
        "version": 1,
        "layers": {
            "constraints": [
                {"category": "c", "content": "x" * (MAX_EXPORT_FILE_BYTES + 100)}
            ]
        },
    }
    with pytest.raises(RulesImportValidationError) as exc:
        parse_rules_import(payload)
    assert exc.value.status_code == 400

    # 原始字符串输入在 json.loads 之前按字节测长
    with pytest.raises(RulesImportValidationError):
        parse_rules_import(json.dumps(payload))


def test_parse_rejects_missing_layers():
    with pytest.raises(RulesImportValidationError):
        parse_rules_import({"format": "sage.rules", "version": 1})
    # project_docs 的键必须来自文件名白名单，防止路径穿越
    with pytest.raises(RulesImportValidationError):
        parse_rules_import(
            {
                "format": "sage.rules",
                "version": 1,
                "layers": {"project_docs": {"../evil.md": "x"}},
            }
        )


def test_parse_accepts_minimal_envelope():
    envelope = parse_rules_import(
        {"format": "sage.rules", "version": 1, "layers": {"constraints": []}}
    )

    assert envelope["format"] == SAGE_RULES_FORMAT
    assert envelope["layers"]["constraints"] == []


def test_diff_marks_new_constraints_as_new():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    envelope = {
        "format": SAGE_RULES_FORMAT,
        "version": SAGE_RULES_VERSION,
        "layers": {
            "constraints": [
                {
                    "category": "风格",
                    "content": "统一使用 ruff",
                    "priority": 5,
                    "enabled": True,
                    "trigger_pattern": None,
                },
            ],
            "project_docs": {},
            "global_rules": "",
        },
    }
    existing = []

    candidates = diff_rules_import(envelope, project, existing)

    assert [c.status for c in candidates] == ["new"]
    assert candidates[0].kind == "constraint"
    assert candidates[0].category == "风格"


def test_diff_marks_duplicate_constraints():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    envelope = {
        "layers": {
            "constraints": [
                {
                    "category": "风格",
                    "content": "统一使用 ruff",
                    "priority": 5,
                    "enabled": True,
                    "trigger_pattern": None,
                },
            ],
            "project_docs": {},
            "global_rules": "",
        },
    }
    existing = [
        _FakeEntry(
            id="constraint:u1",
            layer="constraint",
            source_label="项目规则",
            scope="全局",
            category="风格",
            content="统一使用 ruff",
        ),
    ]

    candidates = diff_rules_import(envelope, project, existing)

    assert candidates[0].status == "duplicate"
    assert candidates[0].duplicate_of == "constraint:u1"


def test_diff_marks_conflict_when_category_matches_but_content_differs():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    envelope = {
        "layers": {
            "constraints": [
                {
                    "category": "风格",
                    "content": "统一使用 black",
                    "priority": 5,
                    "enabled": True,
                    "trigger_pattern": None,
                },
            ],
            "project_docs": {},
            "global_rules": "",
        },
    }
    existing = [
        _FakeEntry(
            id="constraint:u1",
            layer="constraint",
            source_label="项目规则",
            scope="全局",
            category="风格",
            content="统一使用 ruff",
        ),
    ]

    candidates = diff_rules_import(envelope, project, existing)

    assert candidates[0].status == "conflict"
    assert candidates[0].duplicate_of == "constraint:u1"


def test_diff_doc_same_content_is_duplicate():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    envelope = {
        "layers": {
            "constraints": [],
            "project_docs": {"SAGE.md": "# 项目规则\n\n跑 pytest。\n"},
            "global_rules": "",
        },
    }
    existing = [
        _FakeEntry(
            id="doc:SAGE.md#0",
            layer="doc",
            source_label="SAGE.md",
            scope="SAGE.md",
            category="项目规则",
            content="跑 pytest。",
        ),
    ]

    candidates = diff_rules_import(envelope, project, existing)

    doc_candidates = [c for c in candidates if c.kind == "doc"]
    assert doc_candidates[0].status == "duplicate"


def test_diff_doc_different_content_is_conflict():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    envelope = {
        "layers": {
            "constraints": [],
            "project_docs": {"SAGE.md": "# 项目规则\n\n跑 vitest。\n"},
            "global_rules": "",
        },
    }
    existing = [
        _FakeEntry(
            id="doc:SAGE.md#0",
            layer="doc",
            source_label="SAGE.md",
            scope="SAGE.md",
            category="项目规则",
            content="跑 pytest。",
        ),
    ]

    candidates = diff_rules_import(envelope, project, existing)

    doc_candidates = [c for c in candidates if c.kind == "doc"]
    assert doc_candidates[0].status == "conflict"


def test_diff_global_rules_status():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    envelope = {
        "layers": {
            "constraints": [],
            "project_docs": {},
            "global_rules": "# 全局\n\n新偏好。\n",
        },
    }

    candidates_no_existing = diff_rules_import(envelope, project, [])
    assert any(c.kind == "global" and c.status == "new" for c in candidates_no_existing)

    candidates_same = diff_rules_import(
        envelope,
        project,
        [
            _FakeEntry(
                id="global:SAGE.md",
                layer="global",
                source_label="全局规则",
                scope="全局",
                category="全局",
                content="新偏好。",
            )
        ],
    )
    global_same = next(c for c in candidates_same if c.kind == "global")
    assert global_same.status == "duplicate"

    candidates_diff = diff_rules_import(
        envelope,
        project,
        [
            _FakeEntry(
                id="global:SAGE.md",
                layer="global",
                source_label="全局规则",
                scope="全局",
                category="全局",
                content="旧偏好。",
            )
        ],
    )
    global_diff = next(c for c in candidates_diff if c.kind == "global")
    assert global_diff.status == "conflict"


def test_diff_playbook_always_new():
    project = _FakeProject(id="p1", name="sage", path="/tmp/sage")
    envelope = {
        "layers": {
            "constraints": [],
            "project_docs": {},
            "global_rules": "",
            "playbook": {
                "format": "sage.playbook",
                "schema_version": 1,
                "playbook": {"id": "pb-1", "name": "Demo"},
            },
        },
    }

    candidates = diff_rules_import(envelope, project, [])

    playbook_candidates = [c for c in candidates if c.kind == "playbook"]
    assert len(playbook_candidates) == 1
    assert playbook_candidates[0].status == "new"
