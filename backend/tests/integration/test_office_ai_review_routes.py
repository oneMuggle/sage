"""Integration tests for the M3 AI review routes.

Covers ``backend/api/office_ai_review_routes.py`` directly:

- ``POST /ai/review`` with ``use_llm=False`` runs deterministic rules only,
  and writes a history row when ``doc_id`` is provided;
- ``GET /doc/{id}/ai-reviews`` replays history newest-first;
- review against a bound spec reports ``source.kind == "spec"``;
- oversize path / missing file raise OfficePathError / OfficeParseError.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.api import office_ai_review_routes
from backend.api.office_ai_review_routes import (
    AiReviewRequest,
    ai_review_endpoint,
    ai_review_history_endpoint,
)
from backend.data import database as db_mod
from backend.data.database import Database

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
    monkeypatch.setattr(
        office_ai_review_routes, "get_database", db_mod.get_database
    )
    yield db_mod._db.get_connection()
    db_mod._db.close()
    db_mod._db = None


@pytest.fixture(autouse=True)
def _disable_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the LLM factory to report 'not configured' (rule-only path)."""
    monkeypatch.setattr(
        "backend.office.ai_review.build_llm_client_from_settings",
        lambda: None,
    )


def _write_docx(path: Path) -> Path:
    from docx import Document

    doc = Document()
    doc.add_heading("测试文档", level=1)
    doc.add_paragraph("这是一个带占位符【待补充】的段落。")
    doc.add_paragraph("")
    doc.save(str(path))
    return path


def _seed_document(conn, *, doc_id="doc-1", workspace: str):
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata) "
        "VALUES (?, ?, 'word', 'draft.docx', 'draft.docx', 'managed', "
        "1000, 1000, '{}')",
        (doc_id, workspace),
    )
    conn.commit()


# ── review ────────────────────────────────────────────────────────────


async def test_review_rule_only_records_history(conn, workspace: Path):
    docx = _write_docx(workspace / "draft.docx")
    _seed_document(conn, workspace=str(workspace))

    result = await ai_review_endpoint(
        AiReviewRequest(
            workspace_path=str(workspace),
            file_path=str(docx),
            doc_id="doc-1",
            use_llm=False,
        )
    )
    assert result.doc_id == "doc-1"
    assert result.summary.issue_count == len(result.issues)
    assert result.summary.llm_issue_count == 0
    assert result.scope == "full"
    # LLM disabled → at least 'llm_unavailable' is absent because use_llm=False.
    codes = {w["code"] for w in result.warnings}
    assert "llm_unavailable" not in codes

    history = ai_review_history_endpoint("doc-1")
    assert len(history.runs) == 1
    assert history.runs[0].issue_count == result.summary.issue_count
    assert history.runs[0].scope == "full"


async def test_review_without_doc_id_skips_history(conn, workspace: Path):
    docx = _write_docx(workspace / "draft.docx")
    await ai_review_endpoint(
        AiReviewRequest(
            workspace_path=str(workspace),
            file_path=str(docx),
            use_llm=False,
        )
    )
    count = conn.execute("SELECT COUNT(*) FROM office_ai_reviews").fetchone()[0]
    assert count == 0


async def test_review_scope_non_full_falls_back(conn, workspace: Path):
    docx = _write_docx(workspace / "draft.docx")
    result = await ai_review_endpoint(
        AiReviewRequest(
            workspace_path=str(workspace),
            file_path=str(docx),
            scope="selection",
            use_llm=False,
        )
    )
    codes = {w["code"] for w in result.warnings}
    assert "scope_fallback" in codes


async def test_review_missing_file_raises(conn, workspace: Path):
    from backend.office.errors import OfficePathError

    with pytest.raises(OfficePathError):
        await ai_review_endpoint(
            AiReviewRequest(
                workspace_path=str(workspace),
                file_path=str(workspace / "missing.docx"),
                use_llm=False,
            )
        )


async def test_review_outside_workspace_rejected(conn, workspace: Path):
    from backend.office.errors import OfficePathError

    with pytest.raises(OfficePathError):
        await ai_review_endpoint(
            AiReviewRequest(
                workspace_path=str(workspace),
                file_path=str(workspace / "../../etc/passwd"),
                use_llm=False,
            )
        )


async def test_review_oversize_rejected(conn, workspace: Path):
    from backend.office.errors import OfficeParseError

    docx = _write_docx(workspace / "draft.docx")
    with pytest.raises(OfficeParseError):
        await ai_review_endpoint(
            AiReviewRequest(
                workspace_path=str(workspace),
                file_path=str(docx),
                use_llm=False,
                max_size_bytes=1024,  # our test docx is > 1 KiB
            )
        )


# ── spec source ───────────────────────────────────────────────────────


async def test_review_against_bound_spec_uses_spec_rules(conn, workspace: Path):
    """Bind a workspace spec whose pack flags every placeholder paragraph."""
    from backend.api.office_spec_routes import (
        SpecSaveRequest,
        create_spec_endpoint,
    )
    from backend.office.word_rulepack_models import WordRulePack, WordRuleSpec

    pack = WordRulePack(
        id="todo-pack",
        name="TODO 检查",
        rules=[
            WordRuleSpec(
                id="todo",
                title="禁止占位符",
                kind="content.placeholder_residue",
                params={},
                source="§3 占位符",
            )
        ],
    )
    created = create_spec_endpoint(
        SpecSaveRequest(
            workspace_path=str(workspace),
            name="投稿规范",
            pack=pack,
            is_default=True,
        )
    )
    docx = _write_docx(workspace / "draft.docx")
    result = await ai_review_endpoint(
        AiReviewRequest(
            workspace_path=str(workspace),
            file_path=str(docx),
            use_llm=False,
        )
    )
    assert result.spec_id == created.spec.id
    assert any(issue.source.kind == "spec" for issue in result.issues)


# ── history ───────────────────────────────────────────────────────────


def test_history_empty_for_unknown_doc(conn, workspace: Path):
    result = ai_review_history_endpoint("no-such")
    assert result.ok is True
    assert result.runs == []


def test_history_respects_limit(conn, workspace: Path):
    from backend.office.ai_review_history import record

    for i in range(5):
        record("doc-1", scope="full", issue_count=i, conn=conn)
    result = ai_review_history_endpoint("doc-1", limit=2)
    assert len(result.runs) == 2
