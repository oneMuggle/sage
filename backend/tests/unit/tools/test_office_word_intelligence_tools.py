"""Unit tests for Word rule-pack tools (M6)."""

from __future__ import annotations

from pathlib import Path
from typing import List

from docx import Document

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_word_intelligence_tools import (
    OfficeAuditWordTool,
    OfficeBatchAuditTool,
    OfficeExtractRulesTool,
    OfficeFixWordTool,
    OfficeRenderAuditTool,
    OfficeReviseWordTool,
)


def _doc(path: Path, texts: List[str]) -> Path:
    document = Document()
    for text in texts:
        document.add_paragraph(text)
    document.save(str(path))
    return path


def _ctx(tmp_path: Path):
    return set_tool_context(
        ToolExecutionContext(
            session_id="sess-word-tools",
            stream_id="stream-word-tools",
            binding_generation=1,
            office_doc_scope=frozenset(),
        )
    )


def _policy(tmp_path: Path) -> ToolPolicy:
    return ToolPolicy(workspace_root=str(tmp_path))


_TERM_PACK = {
    "id": "inline-pack",
    "name": "Inline pack",
    "rules": [
        {
            "id": "content/terminology",
            "title": "术语统一",
            "category": "content",
            "severity": "warning",
            "kind": "content.terminology",
            "params": {"pairs": [{"preferred": "人工智能", "variants": ["AI"]}]},
            "fixable": True,
        }
    ],
}


def test_tools_require_context(tmp_path: Path) -> None:
    path = _doc(tmp_path / "doc.docx", ["AI 方案"])

    assert not OfficeAuditWordTool(_policy(tmp_path)).execute(file_path=str(path)).success
    assert not OfficeFixWordTool(_policy(tmp_path)).execute(file_path=str(path)).success
    assert (
        not OfficeExtractRulesTool(_policy(tmp_path)).execute(file_path=str(path)).success
    )
    assert not OfficeReviseWordTool(_policy(tmp_path)).execute(file_path=str(path)).success
    assert not OfficeBatchAuditTool(_policy(tmp_path)).execute(
        file_paths=[str(path)]
    ).success
    assert not OfficeRenderAuditTool(_policy(tmp_path)).execute(
        file_path=str(path)
    ).success


# ──────────────────────────────────────────────────────────────────────
# M2 样式模板：规则包 → 画像（READ）+ 已有文档套用（WRITE_LOCAL）
# ──────────────────────────────────────────────────────────────────────

_STYLE_PACK = {
    "id": "style-pack",
    "name": "Style pack",
    "rules": [
        {
            "id": "page/margins",
            "title": "页边距",
            "category": "page",
            "severity": "error",
            "kind": "page.margins",
            "params": {
                "top_cm": 3.0,
                "bottom_cm": 2.5,
                "left_cm": 2.6,
                "right_cm": 2.4,
            },
            "fixable": True,
        },
        {
            "id": "body/font",
            "title": "正文字体",
            "category": "style",
            "severity": "warning",
            "kind": "style.font",
            "params": {
                "style": "Normal",
                "font_east_asia": "宋体",
                "size_pt": 12,
            },
            "fixable": False,
        },
    ],
}


def test_style_tools_require_context(tmp_path: Path) -> None:
    from backend.tools.office_word_intelligence_tools import (
        OfficeApplyWordStyleTool,
        OfficeStyleFromRulepackTool,
    )

    path = _doc(tmp_path / "doc.docx", ["正文"])
    assert not OfficeStyleFromRulepackTool(_policy(tmp_path)).execute(
        rulepack=_STYLE_PACK
    ).success
    assert not OfficeApplyWordStyleTool(_policy(tmp_path)).execute(
        file_path=str(path), format_spec_preset="default"
    ).success


def test_style_from_rulepack_returns_format_spec(tmp_path: Path) -> None:
    from backend.tools.office_word_intelligence_tools import (
        OfficeStyleFromRulepackTool,
    )

    token = _ctx(tmp_path)
    try:
        result = OfficeStyleFromRulepackTool(_policy(tmp_path)).execute(
            rulepack=_STYLE_PACK
        )
    finally:
        reset_tool_context(token)
    assert result.success is True
    spec = result.content["format_spec"]
    assert spec["page"]["margins_cm"]["top"] == 3.0
    assert spec["body"]["font_family"] == "宋体"
    assert spec["body"]["font_size_pt"] == 12
    assert result.content["applied_rule_ids"] == ["page/margins", "body/font"]


def test_apply_word_style_preset_writes_styled_copy(tmp_path: Path) -> None:
    from backend.tools.office_word_intelligence_tools import OfficeApplyWordStyleTool

    path = _doc(tmp_path / "doc.docx", ["正文"])
    token = _ctx(tmp_path)
    try:
        result = OfficeApplyWordStyleTool(_policy(tmp_path)).execute(
            file_path=str(path), format_spec_preset="report"
        )
    finally:
        reset_tool_context(token)
    assert result.success is True
    assert result.content["saved"] is True
    assert Path(result.content["output_path"]).name == "doc-styled.docx"


def test_apply_word_style_requires_spec(tmp_path: Path) -> None:
    from backend.tools.office_word_intelligence_tools import OfficeApplyWordStyleTool

    path = _doc(tmp_path / "doc.docx", ["正文"])
    token = _ctx(tmp_path)
    try:
        result = OfficeApplyWordStyleTool(_policy(tmp_path)).execute(file_path=str(path))
    finally:
        reset_tool_context(token)
    assert result.success is False
    assert "style_spec_required" in result.error


def _seed_style_template(workspace: Path, spec: dict) -> str:
    """把样式模板写进内存库（get_database 读全局 _db）."""
    from backend.data import database as db_mod
    from backend.data.database import Database
    from backend.office.style_template_store import create_style_template

    db_mod._db = Database(":memory:")
    db_mod._db.init_db()
    row = create_style_template(
        db_mod._db.get_connection(),
        workspace_path=str(workspace),
        name="学院模板",
        format_spec=spec,
    )
    return row["id"]


def _drop_seeded_db() -> None:
    from backend.data import database as db_mod

    if db_mod._db is not None:
        db_mod._db.close()
        db_mod._db = None


def test_apply_word_style_uses_workspace_template(tmp_path: Path) -> None:
    from backend.tools.office_word_intelligence_tools import OfficeApplyWordStyleTool

    template_id = _seed_style_template(
        tmp_path, {"body": {"font_family": "微软雅黑", "font_size_pt": 14}}
    )
    try:
        path = _doc(tmp_path / "doc.docx", ["正文"])
        token = _ctx(tmp_path)
        try:
            result = OfficeApplyWordStyleTool(_policy(tmp_path)).execute(
                file_path=str(path), style_template_id=template_id
            )
        finally:
            reset_tool_context(token)
    finally:
        _drop_seeded_db()
    assert result.success is True
    assert result.content["saved"] is True
    assert Path(result.content["output_path"]).name == "doc-styled.docx"


def test_apply_word_style_unknown_template_fails(tmp_path: Path) -> None:
    from backend.tools.office_word_intelligence_tools import OfficeApplyWordStyleTool

    _seed_style_template(tmp_path, {"body": {"font_size_pt": 12}})
    try:
        path = _doc(tmp_path / "doc.docx", ["正文"])
        token = _ctx(tmp_path)
        try:
            result = OfficeApplyWordStyleTool(_policy(tmp_path)).execute(
                file_path=str(path), style_template_id="no-such"
            )
        finally:
            reset_tool_context(token)
    finally:
        _drop_seeded_db()
    assert result.success is False
    assert "style_template_not_found" in result.error


def test_apply_word_style_template_scoped_by_workspace(tmp_path: Path) -> None:
    """其它工作区的模板不能借 id 套用."""
    from backend.tools.office_word_intelligence_tools import OfficeApplyWordStyleTool

    other = tmp_path / "other"
    other.mkdir()
    template_id = _seed_style_template(
        other, {"body": {"font_size_pt": 12}}
    )
    try:
        path = _doc(tmp_path / "doc.docx", ["正文"])
        token = _ctx(tmp_path)
        try:
            result = OfficeApplyWordStyleTool(_policy(tmp_path)).execute(
                file_path=str(path), style_template_id=template_id
            )
        finally:
            reset_tool_context(token)
    finally:
        _drop_seeded_db()
    assert result.success is False
    assert "style_template_not_found" in result.error


def test_audit_tool_returns_anchored_issue(tmp_path: Path) -> None:
    path = _doc(tmp_path / "doc.docx", ["AI 方案"])
    token = _ctx(tmp_path)
    try:
        result = OfficeAuditWordTool(_policy(tmp_path)).execute(
            file_path=str(path), rulepack=_TERM_PACK
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["ok"] is True
    assert result.content["issues"][0]["rule_id"] == "content/terminology"
    assert result.content["issues"][0]["anchor"]["paragraph_index"] == 0


def test_fix_tool_writes_fixed_copy(tmp_path: Path) -> None:
    path = _doc(tmp_path / "doc.docx", ["正文"])
    pack = {
        "id": "margins-pack",
        "name": "Margins",
        "rules": [
            {
                "id": "page/margins",
                "title": "页边距",
                "category": "page",
                "severity": "error",
                "kind": "page.margins",
                "params": {
                    "top_cm": 3.7,
                    "bottom_cm": 3.5,
                    "left_cm": 2.8,
                    "right_cm": 2.6,
                },
                "fixable": True,
            }
        ],
    }
    token = _ctx(tmp_path)
    try:
        result = OfficeFixWordTool(_policy(tmp_path)).execute(
            file_path=str(path), rulepack=pack
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["fixed_count"] == 4
    assert (tmp_path / "doc-fixed.docx").is_file()
    assert result.content["remaining"]["ok"] is True


def test_extract_tool_returns_rules(tmp_path: Path) -> None:
    path = _doc(tmp_path / "spec.docx", ["页面使用 A4 纸张。"])
    token = _ctx(tmp_path)
    try:
        result = OfficeExtractRulesTool(_policy(tmp_path)).execute(
            file_path=str(path), file_type="spec", pack_id="spec-pack"
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["pack"]["id"] == "spec-pack"
    kinds = {rule["kind"] for rule in result.content["pack"]["rules"]}
    assert "page.size" in kinds


def test_revise_tool_writes_tracked_changes(tmp_path: Path) -> None:
    path = _doc(tmp_path / "doc.docx", ["AI 方案"])
    token = _ctx(tmp_path)
    try:
        result = OfficeReviseWordTool(_policy(tmp_path)).execute(
            file_path=str(path), rulepack=_TERM_PACK
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["applied"] == 1
    assert (tmp_path / "doc-revised.docx").is_file()
    assert result.content["remaining"]["ok"] is True


def test_write_tools_reject_outside_workspace(tmp_path: Path) -> None:
    """WRITE 工具（OfficeFixWordTool）仍然拒绝工作区外路径。"""
    token = _ctx(tmp_path)
    try:
        result = OfficeFixWordTool(_policy(tmp_path)).execute(
            file_path="/etc/outside.docx", rulepack=_TERM_PACK
        )
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert "path_outside_workspace" in (result.error or "")


def test_tools_registered_and_visible_to_writer() -> None:
    from backend.agents.profiles import create_default_agents
    from backend.domain.tool_names import ALL_BUILTIN_TOOL_NAMES
    from backend.tools import ToolRegistry, register_all_tools

    names = {
        "office_audit_word",
        "office_fix_word",
        "office_extract_rules",
        "office_revise_word",
        "office_batch_audit",
        "office_render_audit",
        "office_style_from_rulepack",
        "office_apply_word_style",
    }
    registry = ToolRegistry()
    register_all_tools(registry, policy=ToolPolicy())
    assert names <= set(registry.list_names())
    assert names <= set(ALL_BUILTIN_TOOL_NAMES)
    writer = next(p for p in create_default_agents() if p.id == "writer")
    assert names <= set(writer.tools)


def test_batch_audit_scans_workspace_files(tmp_path: Path) -> None:
    _doc(tmp_path / "a.docx", ["AI 方案"])
    _doc(tmp_path / "b.docx", ["正文"])
    token = _ctx(tmp_path)
    try:
        result = OfficeBatchAuditTool(_policy(tmp_path)).execute(
            pattern="**/*.docx", rulepack=_TERM_PACK
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["totals"]["files"] == 2
    assert result.content["totals"]["ok_files"] == 2
    assert result.content["totals"]["issue_count"] >= 1
    assert len(result.content["files"]) == 2
    assert result.content["report_markdown"]


def test_render_audit_degrades_without_converter(tmp_path: Path) -> None:
    path = _doc(tmp_path / "doc.docx", ["正文"])
    token = _ctx(tmp_path)
    try:
        result = OfficeRenderAuditTool(_policy(tmp_path)).execute(file_path=str(path))
    finally:
        reset_tool_context(token)

    # 无 LibreOffice/Word 时 graceful 降级：不报错，rendered=false。
    assert result.success is True
    assert "rendered" in result.content
