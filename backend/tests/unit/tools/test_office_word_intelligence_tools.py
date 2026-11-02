"""Unit tests for Word rule-pack tools (M6)."""

from __future__ import annotations

from pathlib import Path

from docx import Document

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_word_intelligence_tools import (
    OfficeAuditWordTool,
    OfficeExtractRulesTool,
    OfficeFixWordTool,
    OfficeReviseWordTool,
)


def _doc(path: Path, texts: list[str]) -> Path:
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


def test_tools_reject_outside_workspace(tmp_path: Path) -> None:
    token = _ctx(tmp_path)
    try:
        result = OfficeAuditWordTool(_policy(tmp_path)).execute(
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
    }
    registry = ToolRegistry()
    register_all_tools(registry, policy=ToolPolicy())
    assert names <= set(registry.list_names())
    assert names <= set(ALL_BUILTIN_TOOL_NAMES)
    writer = next(p for p in create_default_agents() if p.id == "writer")
    assert names <= set(writer.tools)
