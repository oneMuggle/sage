"""Integration tests for the Word format Linter (Round 10).

Strategy: generate a docx via generate_docx with a known FormatSpec, lint
it against the same spec (expect zero violations), then mutate the request
to violate each rule family (margins / size / orientation / body styles /
heading styles / header text / missing page field / numbering sequence /
caption sequence / citation coverage) and assert the corresponding issue
with rule_id + fix_hint. Also covers the REST endpoint, the agent tool
(incl. workspace fence), and the tool_names/profiles drift gates.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from backend.office.models import OfficeWordGenerateRequest, WordFormatSpec
from backend.office.word import generate_docx
from backend.office.word_lint import lint_docx

_FULL_SPEC = {
    "page": {"size": "A4", "margins_cm": {"top": 2.5, "bottom": 2.5}},
    "body": {"font_size_pt": 12, "line_spacing": 1.5},
    "headings": {"h1": {"font_size_pt": 16, "bold": True}},
    "header": {"text": "内部资料"},
    "footer": {"page_number": True},
    "numbering": True,
}


def _generate(tmp_path: Path, name: str, spec: dict, **kwargs) -> Path:
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename=name,
        title="测试文档",
        format_spec=spec,
        **kwargs,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def _lint(tmp_path: Path, name: str, spec: dict):
    return lint_docx(tmp_path / name, WordFormatSpec(**spec))


def _gen_and_lint(tmp_path: Path, gen_spec: dict, lint_spec: dict, **kwargs):
    name = "doc.docx"
    path = _generate(tmp_path, name, gen_spec, **kwargs)
    assert path.exists()
    return _lint(tmp_path, name, lint_spec)


# ──────────────────────────────────────────────────────────────────────
# Positive: conforming document → zero violations
# ──────────────────────────────────────────────────────────────────────


def test_conforming_document_has_zero_violations(tmp_path: Path) -> None:
    result = _gen_and_lint(
        tmp_path,
        _FULL_SPEC,
        _FULL_SPEC,
        paragraphs=[
            {"text": "引言", "heading": "h1"},
            {"text": "正文", "citations": ["k1"]},
        ],
        references=[{"key": "k1", "title": "文献一", "authors": ["甲"]}],
    )
    assert result.ok, [i.message for i in result.issues]
    assert result.issue_count == 0


def test_empty_spec_checks_nothing(tmp_path: Path) -> None:
    _generate(tmp_path, "any.docx", {})
    result = _lint(tmp_path, "any.docx", {})
    assert result.ok
    assert result.checked_rules == ["citations"]


# ──────────────────────────────────────────────────────────────────────
# Negative: each rule family
# ──────────────────────────────────────────────────────────────────────


def test_margin_violation(tmp_path: Path) -> None:
    gen = {"page": {"margins_cm": {"top": 2.5}}}
    lint = {"page": {"margins_cm": {"top": 3.0}}}
    result = _gen_and_lint(tmp_path, gen, lint)
    rule = next(i for i in result.issues if i.rule_id == "page/margins")
    assert "top" in rule.message
    assert "3.0" in rule.message
    assert rule.fix_hint


def test_page_size_violation(tmp_path: Path) -> None:
    result = _gen_and_lint(tmp_path, {"page": {"size": "A4"}}, {"page": {"size": "letter"}})
    assert any(i.rule_id == "page/size" for i in result.issues)


def test_orientation_violation(tmp_path: Path) -> None:
    result = _gen_and_lint(
        tmp_path, {"page": {"orientation": "portrait"}}, {"page": {"orientation": "landscape"}}
    )
    assert any(i.rule_id == "page/orientation" for i in result.issues)


def test_body_style_violations(tmp_path: Path) -> None:
    result = _gen_and_lint(
        tmp_path,
        {"body": {"font_size_pt": 12, "line_spacing": 1.5}},
        {"body": {"font_size_pt": 10.5, "line_spacing": 2.0}},
    )
    rule_ids = {i.rule_id for i in result.issues}
    assert {"body/font_size", "body/line_spacing"} <= rule_ids


def test_heading_style_violation(tmp_path: Path) -> None:
    result = _gen_and_lint(
        tmp_path,
        {"headings": {"h1": {"font_size_pt": 16}}},
        {"headings": {"h1": {"font_size_pt": 22, "bold": False}}},
    )
    rule_ids = {i.rule_id for i in result.issues}
    assert "headings/h1/font_size" in rule_ids
    assert "headings/h1/bold" in rule_ids


def test_header_text_violation(tmp_path: Path) -> None:
    result = _gen_and_lint(
        tmp_path, {"header": {"text": "A"}}, {"header": {"text": "B"}}
    )
    assert any(i.rule_id == "header/text" for i in result.issues)


def test_missing_page_number_field(tmp_path: Path) -> None:
    _generate(tmp_path, "n.docx", {})
    result = _lint(tmp_path, "n.docx", {"footer": {"page_number": True}})
    assert any(i.rule_id == "footer/page_number" for i in result.issues)


def test_heading_numbering_break_detected(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "num.docx",
        {"numbering": True},
        paragraphs=[
            {"text": "第一章", "heading": "h1"},
            {"text": "手写编号 2 第二章", "heading": "h1"},
        ],
    )
    # 手工破坏编号：第一处是引擎生成的前缀，第二处被替换为错号
    doc = Document(str(path))
    doc.paragraphs[2].text = "3 破坏的标题"
    doc.save(str(path))
    result = lint_docx(path, WordFormatSpec(**{"numbering": True}))
    issues = [i for i in result.issues if i.rule_id == "numbering/sequence"]
    assert issues
    assert "期望 '2'" in issues[0].message


def test_caption_sequence_break_detected(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "cap.docx",
        {},
        paragraphs=[
            {"text": "图1　合法"},
            {"text": "图3　跳号"},
        ],
    )
    result = lint_docx(path, WordFormatSpec(**{"page": {"size": "A4"}}))
    issues = [i for i in result.issues if i.rule_id == "caption/sequence"]
    assert issues
    assert "图" in issues[0].message


def test_citation_gap_warning(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "cite.docx",
        {},
        paragraphs=[{"text": "讨论 [1] 与 [3]。"}],
    )
    result = lint_docx(path, WordFormatSpec())
    issues = [i for i in result.issues if i.rule_id == "citation/coverage"]
    assert issues
    assert issues[0].severity == "warning"
    assert "2" in issues[0].message


# ──────────────────────────────────────────────────────────────────────
# REST endpoint + agent tool + drift gates
# ──────────────────────────────────────────────────────────────────────


def test_lint_endpoint(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.office_routes import lint_word_endpoint, router
    from backend.office.errors import OfficePathError
    from backend.office.models import WordLintRequest

    ws = tmp_path / "ws"
    ws.mkdir()
    doc_path = ws / "doc.docx"
    _generate(tmp_path, "doc.docx", {})  # 占位生成器产物
    doc_path.write_bytes((tmp_path / "doc.docx").read_bytes())

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})
    resp = client.post(
        "/office/word/lint",
        json={
            "workspace_path": str(ws),
            "file_path": str(doc_path),
            "format_spec": {"footer": {"page_number": True}},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert any(i["rule_id"] == "footer/page_number" for i in body["issues"])

    # 工作区围栏：越界 file_path 拒绝（裸 FastAPI 不带全局错误信封，
    # 直接调端点函数断言围栏异常）
    with pytest.raises(OfficePathError):
        lint_word_endpoint(
            WordLintRequest(
                workspace_path=str(ws),
                file_path=str(tmp_path / "doc.docx"),
                format_spec=WordFormatSpec(),
            )
        )


def test_office_lint_tool_roundtrip(tmp_path: Path) -> None:
    from backend.tools.context import ToolExecutionContext, set_tool_context
    from backend.tools.office_lint_tool import OfficeLintWordTool

    tool = OfficeLintWordTool()
    assert tool.schema.name == "office_lint_word"
    path = _generate(tmp_path, "doc.docx", {"footer": {"page_number": True}})

    # requires_tool_context=True：无上下文 fail-closed（office_read_pdf 先例）
    assert not tool.execute(
        file_path=str(path), format_spec={"footer": {"page_number": True}}
    ).success

    token = set_tool_context(
        ToolExecutionContext(
            session_id="sess-lint",
            stream_id="stream-lint",
            binding_generation=1,
            office_doc_scope=frozenset(),
        )
    )
    try:
        result = tool.execute(
            file_path=str(path),
            format_spec={"footer": {"page_number": True}},
        )
        assert result.success, result.error
        assert result.content["ok"] is True
        # 缺参数 fail-fast
        assert not tool.execute(file_path=str(path), format_spec={}).success
    finally:
        from backend.tools.context import reset_tool_context

        reset_tool_context(token)


def test_lint_tool_registered_and_known() -> None:
    """防漂移三件套：注册面 / tool_names / writer profile 三处一致。"""
    from backend.domain.tool_names import ALL_BUILTIN_TOOL_NAMES
    from backend.domain.tool_policy import ToolPolicy
    from backend.tools import ToolRegistry, register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry, policy=ToolPolicy())
    assert "office_lint_word" in set(registry.list_names())
    assert "office_lint_word" in set(ALL_BUILTIN_TOOL_NAMES)

    from backend.agents.profiles import create_default_agents

    writer = next(p for p in create_default_agents() if p.id == "writer")
    assert "office_lint_word" in writer.tools
