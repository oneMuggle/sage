"""Unit tests for the M2 style-template REST endpoints.

Endpoints are invoked directly (same pattern as
``test_word_style_from_rulepack.py``) with an in-memory SQLite database
monkeypatched into ``backend.data.database``. ``apply_style_endpoint`` is
exercised through a stubbed ``apply_style_to_document`` so the merge chain
(template < preset < explicit) can be asserted without touching docx IO.
"""

from __future__ import annotations

import pytest

from backend.api import office_word_style_routes as routes
from backend.data import database as db_mod
from backend.data.database import Database
from backend.office.errors import OfficeGenerateError, OfficeParseError
from backend.office.models import WordFormatSpec

_SPEC = {"body": {"font_family": "宋体", "font_size_pt": 12}}
_SPEC_TEMPLATE = {
    "body": {"font_family": "微软雅黑", "font_size_pt": 14},
    "table_text": {"font_size_pt": 9},
}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_mod._db = Database(":memory:")
    db_mod._db.init_db()
    monkeypatch.setattr(routes, "get_database", lambda: db_mod._db)
    yield db_mod._db
    db_mod._db.close()
    db_mod._db = None


def _create(ws, name="模板A", **kwargs):
    req = routes.WordStyleTemplateSaveRequest(
        workspace_path=str(ws), name=name, **kwargs
    )
    return routes.create_style_template_endpoint(req)


# ── CRUD ──────────────────────────────────────────────────────────────


def test_list_returns_empty_without_workspace(db):
    result = routes.list_style_templates_endpoint(None)
    assert result.ok is True
    assert result.templates == []


def test_create_from_manual_spec_and_list(db, tmp_path):
    created = _create(tmp_path, format_spec=WordFormatSpec(**_SPEC))
    assert created.ok is True
    assert created.template.source_kind == "manual"
    assert created.template.source_ref is None
    assert created.template.format_spec["body"]["font_family"] == "宋体"

    listed = routes.list_style_templates_endpoint(str(tmp_path))
    assert [t.id for t in listed.templates] == [created.template.id]


def test_create_from_preset_derives_source_kind_and_ref(db, tmp_path):
    created = _create(tmp_path, format_spec_preset="report")
    assert created.template.source_kind == "preset"
    assert created.template.source_ref == "report"
    # 预设已展开成画像快照
    assert created.template.format_spec["body"]["font_family"] == "宋体"


def test_create_from_preset_plus_spec_merges_explicit_first(db, tmp_path):
    created = _create(
        tmp_path,
        format_spec_preset="report",
        format_spec=WordFormatSpec(body={"font_family": "仿宋"}),
    )
    body = created.template.format_spec["body"]
    assert body["font_family"] == "仿宋"
    # 预设的其它字段仍在快照里
    assert body["font_size_pt"] == 12


def test_create_from_builtin_rulepack(db, tmp_path):
    created = _create(tmp_path, rulepack_id="gb-t-9704-general")
    assert created.template.source_kind == "rulepack"
    assert created.template.source_ref == "gb-t-9704-general"
    assert created.template.format_spec["body"]["font_family"] == "仿宋_GB2312"


def test_create_rejects_mixed_sources(db, tmp_path):
    with pytest.raises(OfficeParseError):
        _create(
            tmp_path,
            rulepack_id="gb-t-9704-general",
            format_spec_preset="report",
        )


def test_create_rejects_when_no_source(db, tmp_path):
    with pytest.raises(OfficeParseError):
        _create(tmp_path)


def test_create_with_is_default_then_activate_another(db, tmp_path):
    first = _create(tmp_path, name="A", format_spec=WordFormatSpec(**_SPEC))
    second = _create(
        tmp_path,
        name="B",
        format_spec=WordFormatSpec(**_SPEC),
        is_default=True,
    )
    listed = routes.list_style_templates_endpoint(str(tmp_path))
    assert listed.templates[0].id == second.template.id

    activated = routes.activate_style_template_endpoint(
        first.template.id,
        routes.WordStyleTemplateActivateRequest(workspace_path=str(tmp_path)),
    )
    assert activated.template.is_default is True
    listed = routes.list_style_templates_endpoint(str(tmp_path))
    assert listed.templates[0].id == first.template.id


def test_clear_default_endpoint(db, tmp_path):
    _create(tmp_path, format_spec=WordFormatSpec(**_SPEC), is_default=True)
    assert (
        routes.clear_default_style_template_endpoint(str(tmp_path))["ok"] is True
    )
    listed = routes.list_style_templates_endpoint(str(tmp_path))
    assert all(not t.is_default for t in listed.templates)


def test_delete_endpoint(db, tmp_path):
    created = _create(tmp_path, format_spec=WordFormatSpec(**_SPEC))
    result = routes.delete_style_template_endpoint(
        created.template.id, str(tmp_path)
    )
    assert result["ok"] is True
    assert routes.list_style_templates_endpoint(str(tmp_path)).templates == []


def test_delete_unknown_id_raises(db, tmp_path):
    with pytest.raises(OfficeParseError):
        routes.delete_style_template_endpoint("no-such", str(tmp_path))


def test_activate_unknown_id_raises(db, tmp_path):
    with pytest.raises(OfficeParseError):
        routes.activate_style_template_endpoint(
            "no-such",
            routes.WordStyleTemplateActivateRequest(workspace_path=str(tmp_path)),
        )


# ── style/apply 合并链 ───────────────────────────────────────────────


@pytest.fixture()
def applied(monkeypatch):
    """捕获 apply_style_to_document 的 spec，不落盘."""
    captured = {}

    def fake_apply(path, spec, **kwargs):
        captured["path"] = path
        captured["spec"] = spec
        captured["kwargs"] = kwargs
        return {"ok": True, "styles_changed": 0}

    monkeypatch.setattr(routes, "apply_style_to_document", fake_apply)
    return captured


def _apply_req(file_path, **kwargs):
    return routes.WordStyleApplyRequest(file_path=file_path, **kwargs)


def test_apply_with_template_only(db, tmp_path, applied):
    created = _create(tmp_path, format_spec=WordFormatSpec(**_SPEC_TEMPLATE))
    out = routes.apply_style_endpoint(
        _apply_req(
            str(tmp_path / "a.docx"),
            workspace_path=str(tmp_path),
            style_template_id=created.template.id,
        )
    )
    assert out["ok"] is True
    spec = applied["spec"]
    assert isinstance(spec, WordFormatSpec)
    assert spec.body.font_family == "微软雅黑"
    assert spec.body.font_size_pt == 14


def test_apply_template_then_preset_overrides(db, tmp_path, applied):
    created = _create(tmp_path, format_spec=WordFormatSpec(**_SPEC_TEMPLATE))
    routes.apply_style_endpoint(
        _apply_req(
            str(tmp_path / "a.docx"),
            workspace_path=str(tmp_path),
            style_template_id=created.template.id,
            format_spec_preset="report",
        )
    )
    spec = applied["spec"]
    # 预设显式字段覆盖模板
    assert spec.body.font_family == "宋体"
    # 模板里预设未触达的字段保留
    assert spec.table_text.font_size_pt == 9


def test_apply_explicit_spec_wins_over_all(db, tmp_path, applied):
    created = _create(tmp_path, format_spec=WordFormatSpec(**_SPEC_TEMPLATE))
    routes.apply_style_endpoint(
        _apply_req(
            str(tmp_path / "a.docx"),
            workspace_path=str(tmp_path),
            style_template_id=created.template.id,
            format_spec_preset="report",
            format_spec=WordFormatSpec(body={"font_size_pt": 16}),
        )
    )
    spec = applied["spec"]
    assert spec.body.font_size_pt == 16
    assert spec.body.font_family == "宋体"
    assert spec.table_text.font_size_pt == 9


def test_apply_template_requires_workspace(db, tmp_path, applied):
    created = _create(tmp_path, format_spec=WordFormatSpec(**_SPEC))
    with pytest.raises(OfficeParseError):
        routes.apply_style_endpoint(
            _apply_req(
                str(tmp_path / "a.docx"), style_template_id=created.template.id
            )
        )


def test_apply_unknown_template_raises(db, tmp_path, applied):
    with pytest.raises(OfficeParseError):
        routes.apply_style_endpoint(
            _apply_req(
                str(tmp_path / "a.docx"),
                workspace_path=str(tmp_path),
                style_template_id="no-such",
            )
        )


def test_apply_cross_workspace_template_rejected(db, tmp_path, applied):
    other = tmp_path / "other"
    other.mkdir()
    created = _create(other, format_spec=WordFormatSpec(**_SPEC))
    with pytest.raises(OfficeParseError):
        routes.apply_style_endpoint(
            _apply_req(
                str(tmp_path / "a.docx"),
                workspace_path=str(tmp_path),
                style_template_id=created.template.id,
            )
        )


def test_apply_without_any_source_raises(db, tmp_path, applied):
    with pytest.raises(OfficeGenerateError):
        routes.apply_style_endpoint(_apply_req(str(tmp_path / "a.docx")))


def test_apply_passes_options_through(db, tmp_path, applied):
    created = _create(tmp_path, format_spec=WordFormatSpec(**_SPEC))
    routes.apply_style_endpoint(
        _apply_req(
            str(tmp_path / "a.docx"),
            workspace_path=str(tmp_path),
            style_template_id=created.template.id,
            clear_direct_formatting=True,
            dry_run=True,
            overwrite=True,
            output_filename="out.docx",
        )
    )
    kwargs = applied["kwargs"]
    assert kwargs["clear_direct_formatting"] is True
    assert kwargs["dry_run"] is True
    assert kwargs["overwrite"] is True
    assert kwargs["output_filename"] == "out.docx"
