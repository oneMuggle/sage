"""Integration tests for the M2.5 spec library routes.

Covers ``backend/api/office_spec_routes.py`` directly (no TestClient) with
an in-memory SQLite connection wired into the route module and a per-test
workspace directory for rulepack JSON storage:

- POST/GET/DELETE ``/specs`` CRUD;
- ``/specs/{id}/activate`` + ``DELETE /specs/default``;
- ``/doc/{id}/spec`` binding round trip;
- ``/specs/extract`` from a real .docx (LLM off).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.api import office_spec_routes
from backend.api.office_spec_routes import (
    SpecActivateRequest,
    SpecBindRequest,
    SpecExtractRequest,
    SpecSaveRequest,
    SpecUpdateRequest,
    activate_spec_endpoint,
    bind_doc_spec_endpoint,
    clear_default_spec_endpoint,
    create_spec_endpoint,
    delete_spec_endpoint,
    extract_spec_endpoint,
    get_doc_spec_endpoint,
    get_spec_endpoint,
    list_specs_endpoint,
    update_spec_endpoint,
)
from backend.data import database as db_mod
from backend.data.database import Database
from backend.office.word_rulepack_models import WordRulePack, WordRuleSpec

pytestmark = pytest.mark.integration


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture()
def conn(monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    db_mod._db = Database(":memory:")
    db_mod._db.init_db()
    # Route module resolves get_database() at call time.
    monkeypatch.setattr(office_spec_routes, "get_database", db_mod.get_database)
    yield db_mod._db.get_connection()
    db_mod._db.close()
    db_mod._db = None


def _make_pack() -> WordRulePack:
    return WordRulePack(
        id="ws-spec-pack",
        name="投稿规范（测试）",
        version="1.0",
        rules=[
            WordRuleSpec(
                id="margins",
                title="页边距 2.54cm",
                kind="page.margins",
                params={"top_cm": 2.54, "bottom_cm": 2.54},
                source="§1.2 页边距",
            ),
            WordRuleSpec(
                id="heading",
                title="一级标题采用标题 1 样式",
                kind="structure.required_headings",
                params={"required": ["引言", "方法"]},
                source="§2 结构要求",
            ),
        ],
    )


def _seed_document(conn, *, doc_id="doc-1", workspace: str, spec_id=None):
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata, "
        "active_spec_id) "
        "VALUES (?, ?, 'word', 'draft.docx', 'draft.docx', 'managed', "
        "1000, 1000, '{}', ?)",
        (doc_id, workspace, spec_id),
    )
    conn.commit()


# ── CRUD ──────────────────────────────────────────────────────────────


def test_list_empty_initially(conn, workspace: Path):
    result = list_specs_endpoint(workspace_path=str(workspace))
    assert result.ok is True
    assert result.specs == []
    assert result.workspace_path == str(workspace)


def test_create_from_existing_rulepack_id(conn, workspace: Path):
    result = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="通用投稿规范",
            rulepack_id="general-quality",
        )
    )
    assert result.spec.rulepack_id == "general-quality"
    assert result.rulepack is not None

    detail = get_spec_endpoint(result.spec.id, workspace_path=str(workspace))
    assert detail.spec.name == "通用投稿规范"


def test_create_from_pack_saves_rulepack_first(conn, workspace: Path):
    pack = _make_pack()
    result = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="投稿规范",
            pack=pack,
        )
    )
    assert result.spec.rulepack_id == "ws-spec-pack"
    assert result.rulepack is not None
    assert len(result.rulepack.rules) == 2
    pack_file = workspace / ".sage" / "word-rulepacks" / "ws-spec-pack.json"
    assert pack_file.is_file()


def test_create_from_pack_without_source_rejected(conn, workspace: Path):
    pack = WordRulePack(
        id="no-source",
        name="无来源",
        rules=[
            WordRuleSpec(
                id="r1",
                title="页边距",
                kind="page.margins",
                source="",
            )
        ],
    )
    from backend.office.errors import OfficeParseError

    with pytest.raises(OfficeParseError):
        create_spec_endpoint(
            SpecSaveRequest(
                workspace_path=str(workspace), name="x", pack=pack
            )
        )


def test_create_requires_pack_or_rulepack_id(conn, workspace: Path):
    from backend.office.errors import OfficeParseError

    with pytest.raises(OfficeParseError):
        create_spec_endpoint(
            SpecSaveRequest(workspace_path=str(workspace), name="x")
        )


def test_update_name(conn, workspace: Path):
    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="Old Name",
            rulepack_id="general-quality",
        )
    )
    updated = update_spec_endpoint(
        created.spec.id,
        SpecUpdateRequest(workspace_path=str(workspace), name="New Name"),
    )
    assert updated.spec.name == "New Name"


def test_update_nonexistent_raises(conn, workspace: Path):
    from backend.office.errors import OfficeParseError

    with pytest.raises(OfficeParseError):
        update_spec_endpoint(
            "no-such",
            SpecUpdateRequest(workspace_path=str(workspace), name="x"),
        )


def test_delete_and_404_after(conn, workspace: Path):
    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="Del",
            rulepack_id="general-quality",
        )
    )
    from backend.office.errors import OfficeParseError

    out = delete_spec_endpoint(created.spec.id, workspace_path=str(workspace))
    assert out["ok"] is True
    with pytest.raises(OfficeParseError):
        get_spec_endpoint(created.spec.id, workspace_path=str(workspace))


# ── activate / clear ─────────────────────────────────────────────────


def test_activate_sets_default(conn, workspace: Path):
    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="A",
            rulepack_id="general-quality",
        )
    )
    activated = activate_spec_endpoint(
        created.spec.id,
        SpecActivateRequest(workspace_path=str(workspace)),
    )
    assert activated.is_default is True
    listed = list_specs_endpoint(workspace_path=str(workspace))
    assert listed.specs[0].id == created.spec.id


def test_clear_default(conn, workspace: Path):
    create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="A",
            rulepack_id="general-quality",
            is_default=True,
        )
    )
    out = clear_default_spec_endpoint(workspace_path=str(workspace))
    assert out["ok"] is True
    assert out["default"] is None


def test_clear_default_route_declared_before_param_route():
    """FastAPI 按声明顺序匹配：DELETE /specs/default 必须先于 /specs/{spec_id}."""
    delete_paths = [
        route.path
        for route in office_spec_routes.router.routes
        if "DELETE" in getattr(route, "methods", set())
    ]
    assert delete_paths.index("/specs/default") < delete_paths.index(
        "/specs/{spec_id}"
    )


# ── doc binding ──────────────────────────────────────────────────────


def test_bind_and_unbind(conn, workspace: Path):
    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="A",
            rulepack_id="general-quality",
        )
    )
    _seed_document(conn, workspace=str(workspace))

    bound = bind_doc_spec_endpoint(
        "doc-1",
        SpecBindRequest(workspace_path=str(workspace), spec_id=created.spec.id),
    )
    assert bound.spec_id == created.spec.id
    assert bound.effective_spec is not None
    assert bound.effective_spec.id == created.spec.id

    got = get_doc_spec_endpoint("doc-1", workspace_path=str(workspace))
    assert got.spec_id == created.spec.id

    unbound = bind_doc_spec_endpoint(
        "doc-1", SpecBindRequest(workspace_path=str(workspace), spec_id=None)
    )
    assert unbound.spec_id is None
    assert unbound.effective_spec is None


def test_bind_nonexistent_spec_raises(conn, workspace: Path):
    from backend.office.errors import OfficeParseError

    _seed_document(conn, workspace=str(workspace))
    with pytest.raises(OfficeParseError):
        bind_doc_spec_endpoint(
            "doc-1",
            SpecBindRequest(workspace_path=str(workspace), spec_id="no-such"),
        )


# ── cross-workspace isolation (security review H1/H2) ────────────────


@pytest.fixture()
def workspace2(tmp_path: Path) -> Path:
    ws = tmp_path / "ws2"
    ws.mkdir()
    return ws


def test_get_spec_cross_workspace_raises(conn, workspace: Path, workspace2: Path):
    from backend.office.errors import OfficeParseError

    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="WS1 Spec",
            rulepack_id="general-quality",
        )
    )
    with pytest.raises(OfficeParseError):
        get_spec_endpoint(created.spec.id, workspace_path=str(workspace2))


def test_update_spec_cross_workspace_raises(
    conn, workspace: Path, workspace2: Path
):
    from backend.office.errors import OfficeParseError

    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="WS1 Spec",
            rulepack_id="general-quality",
        )
    )
    with pytest.raises(OfficeParseError):
        update_spec_endpoint(
            created.spec.id,
            SpecUpdateRequest(workspace_path=str(workspace2), name="Hacked"),
        )
    detail = get_spec_endpoint(created.spec.id, workspace_path=str(workspace))
    assert detail.spec.name == "WS1 Spec"


def test_delete_spec_cross_workspace_raises(
    conn, workspace: Path, workspace2: Path
):
    from backend.office.errors import OfficeParseError

    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="WS1 Spec",
            rulepack_id="general-quality",
        )
    )
    with pytest.raises(OfficeParseError):
        delete_spec_endpoint(created.spec.id, workspace_path=str(workspace2))
    detail = get_spec_endpoint(created.spec.id, workspace_path=str(workspace))
    assert detail.spec.id == created.spec.id


def test_bind_doc_in_other_workspace_rejected(
    conn, workspace: Path, workspace2: Path
):
    from backend.office.errors import OfficeParseError

    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace2),
            name="WS2 Spec",
            rulepack_id="general-quality",
        )
    )
    _seed_document(conn, doc_id="doc-ws1", workspace=str(workspace))
    with pytest.raises(OfficeParseError):
        bind_doc_spec_endpoint(
            "doc-ws1",
            SpecBindRequest(
                workspace_path=str(workspace), spec_id=created.spec.id
            ),
        )
    got = get_doc_spec_endpoint("doc-ws1", workspace_path=str(workspace))
    assert got.spec_id is None


def test_get_doc_spec_cross_workspace_hides_binding(
    conn, workspace: Path, workspace2: Path
):
    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="WS1 Spec",
            rulepack_id="general-quality",
        )
    )
    _seed_document(
        conn, doc_id="doc-ws1", workspace=str(workspace), spec_id=created.spec.id
    )
    got = get_doc_spec_endpoint("doc-ws1", workspace_path=str(workspace2))
    assert got.spec_id is None
    assert got.effective_spec is None


# ── extract ───────────────────────────────────────────────────────────


def _write_docx(path: Path) -> Path:
    from docx import Document

    doc = Document()
    doc.add_heading("投稿要求", level=1)
    doc.add_paragraph("1. 页边距上下各 2.54 cm。")
    doc.add_paragraph("2. 标题使用标题 1 样式。")
    doc.save(str(path))
    return path


def test_extract_rulepack_from_docx(conn, workspace: Path):
    docx = _write_docx(workspace / "spec.docx")
    req = SpecExtractRequest(
        workspace_path=str(workspace),
        file_path=str(docx),
        pack_id="extracted",
        pack_name="提取草稿",
        use_llm=False,
    )
    result = extract_spec_endpoint(req)
    assert result.ok is True
    assert result.pack.id == "extracted"


def test_extract_path_escape_rejected(conn, workspace: Path):
    from backend.office.errors import OfficePathError

    with pytest.raises(OfficePathError):
        extract_spec_endpoint(
            SpecExtractRequest(
                workspace_path=str(workspace),
                file_path=str(workspace / "../../etc/passwd"),
                use_llm=False,
            )
        )
