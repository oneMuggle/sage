"""PresentationTemplateRegistry 测试 —— 伪造技能模板目录 + 独立临时库。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.services.presentation_service import PresentationInputError
from backend.services.presentation_template_registry import (
    PresentationTemplateRegistry,
    TemplateEntry,
)


def _write_template(
    base: Path,
    dir_name: str,
    template_id: str,
    *,
    index_meta: dict,
    frontmatter: dict | None = None,
    with_spec: bool = True,
) -> Path:
    """在 ``base/<dir_name>/`` 下造一个模板条目（含索引与可选 spec）。"""
    base.mkdir(parents=True, exist_ok=True)
    index_path = base / f"{dir_name}_index.json"
    index = {}
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    index[template_id] = index_meta
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    root = base / template_id
    if with_spec:
        spec = root / "templates" / "design_spec.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        lines = ["---"]
        for key, value in (frontmatter or {}).items():
            lines.append(f"{key}: {value}")
        lines.append("---")
        lines.append("")
        lines.append("# spec")
        spec.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _registry(skill_root: Path, db) -> PresentationTemplateRegistry:
    return PresentationTemplateRegistry(conn_factory=db.get_connection, skill_root=skill_root)


# --------------------------------------------------------------------------- #
# 扫描 / 刷新
# --------------------------------------------------------------------------- #
def test_refresh_persists_all_kinds(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(
        skill / "templates" / "brands",
        "brands",
        "acme",
        index_meta={"summary": "品牌 A", "primary_color": "#112233"},
        frontmatter={"kind": "brand", "keywords": "[a, b]"},
    )
    _write_template(
        skill / "templates" / "styles",
        "styles",
        "clean",
        index_meta={"summary": "简洁", "keywords": ["minimal"]},
    )
    _write_template(
        skill / "templates" / "layouts",
        "layouts",
        "brief",
        index_meta={"summary": "两页结构", "canvas_format": "16:9", "page_count": 2},
        frontmatter={"page_types": "[cover, content]"},
    )
    _write_template(
        skill / "templates" / "decks",
        "decks",
        "demo",
        index_meta={"summary": "整套", "page_count": 5},
    )

    registry = _registry(skill, setup_test_db)
    assert registry.refresh() == 4

    entries = {e.template_id: e for e in registry.list_templates()}
    assert set(entries) == {"acme", "clean", "brief", "demo"}
    assert entries["acme"].primary_color == "#112233"
    assert entries["brief"].canvas_format == "16:9"
    assert entries["brief"].page_count == 2
    assert entries["brief"].page_types == ("cover", "content")
    assert entries["brief"].name == "brief"  # 无 name 字段 -> 用 template_id
    assert Path(entries["brief"].root_path).is_dir()


def test_refresh_tolerates_missing_kind_dirs(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(skill / "templates" / "brands", "brands", "acme", index_meta={"summary": "A"})
    registry = _registry(skill, setup_test_db)

    assert registry.refresh() == 1
    assert registry.list_templates("style") == []


def test_entries_without_design_spec_are_skipped(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(skill / "templates" / "brands", "brands", "ok", index_meta={"summary": "ok"})
    _write_template(
        skill / "templates" / "brands",
        "brands",
        "broken",
        index_meta={"summary": "broken"},
        with_spec=False,
    )
    registry = _registry(skill, setup_test_db)

    assert registry.refresh() == 1
    assert [e.template_id for e in registry.list_templates()] == ["ok"]


def test_frontmatter_fills_missing_index_fields(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(
        skill / "templates" / "decks",
        "decks",
        "demo",
        index_meta={},
        frontmatter={"summary": "来自 frontmatter", "page_count": 3},
    )
    registry = _registry(skill, setup_test_db)
    registry.refresh()

    (entry,) = registry.list_templates()
    assert entry.summary == "来自 frontmatter"
    assert entry.page_count == 3


def test_local_scope_overrides_builtin(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(
        skill / "templates" / "brands", "brands", "acme", index_meta={"summary": "内置"}
    )
    local_base = skill / "templates" / "local" / "brands"
    _write_template(local_base, "brands", "acme", index_meta={"summary": "本地覆盖"})

    registry = _registry(skill, setup_test_db)
    assert registry.refresh() == 1
    (entry,) = registry.list_templates()
    assert entry.summary == "本地覆盖"
    assert Path(entry.root_path).parent.parent.name == "local"


def test_refresh_replaces_previous_rows(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(skill / "templates" / "brands", "brands", "old", index_meta={"summary": "旧"})
    registry = _registry(skill, setup_test_db)
    registry.refresh()

    (skill / "templates" / "brands" / "brands_index.json").write_text(
        json.dumps({}), encoding="utf-8"
    )
    assert registry.refresh() == 0
    assert registry.list_templates() == []


def test_ensure_fresh_only_scans_when_empty(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(skill / "templates" / "brands", "brands", "acme", index_meta={"summary": "A"})
    calls = []

    class CountingRegistry(PresentationTemplateRegistry):
        def refresh(self) -> int:
            calls.append(1)
            return super().refresh()

    registry = CountingRegistry(conn_factory=setup_test_db.get_connection, skill_root=skill)
    registry.ensure_fresh()
    registry.ensure_fresh()

    assert len(calls) == 1
    assert len(registry.list_templates()) == 1


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def test_list_templates_rejects_unknown_kind(setup_test_db, tmp_path: Path):
    registry = _registry(tmp_path / "skill", setup_test_db)
    with pytest.raises(PresentationInputError, match="未知模板种类"):
        registry.list_templates("gallery")


# --------------------------------------------------------------------------- #
# resolve_roots
# --------------------------------------------------------------------------- #
def _seed_library(setup_test_db, tmp_path: Path) -> PresentationTemplateRegistry:
    skill = tmp_path / "skill"
    _write_template(skill / "templates" / "brands", "brands", "acme", index_meta={"summary": "A"})
    _write_template(
        skill / "templates" / "layouts", "layouts", "brief", index_meta={"summary": "B"}
    )
    registry = _registry(skill, setup_test_db)
    registry.refresh()
    return registry


def test_resolve_roots_returns_dirs(setup_test_db, tmp_path: Path):
    registry = _seed_library(setup_test_db, tmp_path)
    roots = registry.resolve_roots(["brand:acme", "layout:brief"])

    assert len(roots) == 2
    assert all(root.is_dir() for root in roots)
    assert [root.name for root in roots] == ["acme", "brief"]


def test_resolve_roots_empty_is_empty(setup_test_db, tmp_path: Path):
    registry = _seed_library(setup_test_db, tmp_path)
    assert registry.resolve_roots([]) == []


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        (["acme"], "应形如"),
        (["gallery:x"], "未知模板种类"),
        (["brand:nope"], "未知模板"),
    ],
)
def test_resolve_roots_rejects_invalid_selection(setup_test_db, tmp_path: Path, selection, message):
    registry = _seed_library(setup_test_db, tmp_path)
    with pytest.raises(PresentationInputError, match=message):
        registry.resolve_roots(selection)


def test_resolve_roots_rejects_duplicate_kind(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(skill / "templates" / "brands", "brands", "a", index_meta={"summary": "A"})
    _write_template(skill / "templates" / "brands", "brands", "b", index_meta={"summary": "B"})
    registry = _registry(skill, setup_test_db)
    registry.refresh()

    with pytest.raises(PresentationInputError, match="同一类模板"):
        registry.resolve_roots(["brand:a", "brand:b"])


def test_resolve_roots_rejects_deleted_directory(setup_test_db, tmp_path: Path):
    registry = _seed_library(setup_test_db, tmp_path)
    (entry,) = (e for e in registry.list_templates() if e.template_id == "acme")
    shutil.rmtree(entry.root_path)

    with pytest.raises(PresentationInputError, match="已不存在"):
        registry.resolve_roots(["brand:acme"])


def test_row_roundtrip_preserves_page_types(setup_test_db, tmp_path: Path):
    skill = tmp_path / "skill"
    _write_template(
        skill / "templates" / "layouts",
        "layouts",
        "brief",
        index_meta={"summary": "B", "page_types": ["cover", "content"]},
    )
    registry = _registry(skill, setup_test_db)
    registry.refresh()

    (entry,) = registry.list_templates()
    assert isinstance(entry, TemplateEntry)
    assert entry.page_types == ("cover", "content")
