"""Integration tests for Word rule pack + audit routes (M2a)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from backend.api.office_word_audit_routes import (
    WordAuditRequest,
    WordRulePackSaveRequest,
    audit_word_endpoint,
    delete_rulepack_endpoint,
    get_rulepack_endpoint,
    list_rulepacks_endpoint,
    save_rulepack_endpoint,
)
from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.word_rulepack_models import WordRulePack, WordRuleSpec


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _save_doc(workspace: Path, name: str, text: str = "正文") -> Path:
    document = Document()
    document.add_paragraph(text)
    path = workspace / name
    document.save(str(path))
    return path


def _rule(rule_id: str, kind: str, params: dict = None) -> WordRuleSpec:
    return WordRuleSpec(id=rule_id, title=rule_id, kind=kind, params=params or {})


def _workspace_pack() -> WordRulePack:
    return WordRulePack(
        id="ws-pack",
        name="Workspace pack",
        rules=[_rule("content/placeholder_residue", "content.placeholder_residue")],
    )


def test_rulepack_list_detail_and_audit(workspace: Path) -> None:
    listing = list_rulepacks_endpoint(workspace_path=str(workspace))
    ids = {pack.id for pack in listing.packs}
    assert {"gb-t-9704-general", "general-quality"} <= ids
    assert all(pack.origin == "builtin" for pack in listing.packs)

    detail = get_rulepack_endpoint(
        pack_id="general-quality", workspace_path=str(workspace)
    )
    assert detail.origin == "builtin"
    assert detail.pack.id == "general-quality"

    path = _save_doc(workspace, "residue.docx", "残留 {{name}}")
    result = audit_word_endpoint(
        WordAuditRequest(
            workspace_path=str(workspace),
            file_path=str(path),
            rulepack_id="general-quality",
        )
    )
    assert result.ok is False
    assert any(issue.rule_id == "content/placeholder_residue" for issue in result.issues)
    assert any(issue.anchor is not None for issue in result.issues)

    clean_pack = WordRulePack(
        id="inline-clean",
        name="Inline clean",
        rules=[_rule("content/placeholder_residue", "content.placeholder_residue")],
    )
    clean = audit_word_endpoint(
        WordAuditRequest(
            workspace_path=str(workspace),
            file_path=str(_save_doc(workspace, "clean.docx")),
            rulepack=clean_pack,
        )
    )
    assert clean.ok is True
    assert clean.rule_pack_id == "inline-clean"
    assert clean.issues == []


def test_workspace_rulepack_save_load_delete(workspace: Path) -> None:
    saved = save_rulepack_endpoint(
        WordRulePackSaveRequest(workspace_path=str(workspace), pack=_workspace_pack())
    )
    assert saved.origin == "workspace"
    assert saved.pack.id == "ws-pack"

    listing = list_rulepacks_endpoint(workspace_path=str(workspace))
    workspace_items = [pack for pack in listing.packs if pack.origin == "workspace"]
    assert [pack.id for pack in workspace_items] == ["ws-pack"]

    loaded = get_rulepack_endpoint(pack_id="ws-pack", workspace_path=str(workspace))
    assert loaded.origin == "workspace"
    assert loaded.pack.rules[0].kind == "content.placeholder_residue"

    audit = audit_word_endpoint(
        WordAuditRequest(
            workspace_path=str(workspace),
            file_path=str(_save_doc(workspace, "ws.docx", "残留 <<x>>")),
            rulepack_id="ws-pack",
        )
    )
    assert audit.rule_pack_id == "ws-pack"
    assert audit.ok is False

    deleted = delete_rulepack_endpoint(pack_id="ws-pack", workspace_path=str(workspace))
    assert deleted == {"ok": True, "id": "ws-pack"}
    with pytest.raises(OfficeFileNotFoundError):
        get_rulepack_endpoint(pack_id="ws-pack", workspace_path=str(workspace))


def test_audit_rejects_missing_pack_bad_kind_size_and_escape(workspace: Path) -> None:
    path = _save_doc(workspace, "doc.docx")

    with pytest.raises(OfficeFileNotFoundError):
        audit_word_endpoint(
            WordAuditRequest(
                workspace_path=str(workspace),
                file_path=str(path),
                rulepack_id="missing-pack",
            )
        )

    with pytest.raises(OfficeParseError):
        audit_word_endpoint(
            WordAuditRequest(
                workspace_path=str(workspace),
                file_path=str(path),
                rulepack=WordRulePack(
                    id="bad",
                    name="Bad",
                    rules=[_rule("bad-kind", "page.unknown")],
                ),
            )
        )

    with pytest.raises(OfficeSizeLimitError):
        audit_word_endpoint(
            WordAuditRequest(
                workspace_path=str(workspace),
                file_path=str(path),
                max_size_bytes=1024,
            )
        )

    with pytest.raises(OfficePathError):
        audit_word_endpoint(
            WordAuditRequest(
                workspace_path=str(workspace),
                file_path="../outside.docx",
            )
        )
