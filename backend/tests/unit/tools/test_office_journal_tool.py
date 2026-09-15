# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for :mod:`backend.tools.office_journal_tool`.

覆盖范围：
- 4 个工具的 schema 形态与 risk/requires_tool_context 元数据
- parse_template：缺 file_path → content_shape_invalid；越界 → blocked；OK → spec dict
- fill_from_content：缺 content → content_shape_invalid；shape 非法 → content_shape_invalid；
  缺绑定 → workspace_not_bound
- validate：缺 file_path / spec_id → 错误；workspace_not_bound；正常返回 violations
- generate_article：缺 user_request / workspace_not_bound；adapter 不可用 → 错；
  跑通时返回 gen_id/spec_id/output_path
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.office.session_workspace import bind_session_workspace
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_journal_tool import (
    OfficeJournalFillFromContentTool,
    OfficeJournalGenerateArticleTool,
    OfficeJournalParseTemplateTool,
    OfficeJournalValidateTool,
)

pytestmark = pytest.mark.unit

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "journal"
TEMPLATE_PATH = FIXTURE_ROOT / "simple_chinese_template.docx"
GOOD_FILLED = FIXTURE_ROOT / "good_filled_paper.docx"


# ── Helpers ───────────────────────────────────────────────────────────


class _StubLLM:
    """替代 JournalLLMAdapter 的最小 stub。"""

    async def generate(self, **_kwargs: Any) -> dict:
        return {
            "title": "stub title",
            "abstract": "stub abstract",
            "sections": {"关键词": "k1, k2"},
            "references": [],
            "citations": [],
        }


def _setup_workspace(tmp_path: Path, session_id: str = "sess-test") -> Path:
    """建临时 workspace + bind 到 session_id；返回 canonical 路径。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    db = get_database()
    conn = db.get_connection()
    # 必须先把 session 注入 sessions 表，否则 bind_session_workspace 报
    # WorkspaceSessionNotFoundError（与 office_archive_tool 同模式）。
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()
    bind_session_workspace(
        conn,
        session_id=session_id,
        workspace_path=str(ws.resolve()),
    )
    return ws


def _ctx(session_id: str = "sess-test") -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-test",
        binding_generation=1,
        office_doc_scope="read_write",
    )


def _clear_context() -> None:
    """测试间强清空 ToolExecutionContext（不依赖 token 配对）。"""
    from backend.tools.context import _tool_context_var  # type: ignore[attr-defined]

    _tool_context_var.set(None)


def _content() -> Dict[str, Any]:
    return {
        "title": "测试论文",
        "abstract": "这是测试摘要，必须非空。",
        "sections": {"关键词": "测试, 关键词"},
        "references": [],
        "citations": [],
    }


def _tool_parse(**policy_kwargs: Any) -> OfficeJournalParseTemplateTool:
    return OfficeJournalParseTemplateTool(policy=ToolPolicy(workspace_root=None, **policy_kwargs))


def _tool_fill(**policy_kwargs: Any) -> OfficeJournalFillFromContentTool:
    return OfficeJournalFillFromContentTool(policy=ToolPolicy(workspace_root=None, **policy_kwargs))


def _tool_validate(**policy_kwargs: Any) -> OfficeJournalValidateTool:
    return OfficeJournalValidateTool(policy=ToolPolicy(workspace_root=None, **policy_kwargs))


def _tool_generate(**policy_kwargs: Any) -> OfficeJournalGenerateArticleTool:
    return OfficeJournalGenerateArticleTool(policy=ToolPolicy(workspace_root=None, **policy_kwargs))


# ── Schema / metadata ─────────────────────────────────────────────────


def test_parse_template_schema_shape():
    tool = _tool_parse()
    s = tool._build_schema()
    assert s.name == "office_journal_parse_template"
    assert "file_path" in s.parameters["properties"]
    assert s.parameters["required"] == ["file_path"]


def test_fill_from_content_schema_shape():
    tool = _tool_fill()
    s = tool._build_schema()
    assert s.name == "office_journal_fill_from_content"
    assert "content" in s.parameters["properties"]
    assert "spec_id" in s.parameters["properties"]


def test_generate_article_schema_shape():
    tool = _tool_generate()
    s = tool._build_schema()
    assert s.name == "office_journal_generate_article"
    assert "user_request" in s.parameters["properties"]
    assert "max_rounds" in s.parameters["properties"]


def test_validate_schema_shape():
    tool = _tool_validate()
    s = tool._build_schema()
    assert s.name == "office_journal_validate"
    assert "file_path" in s.parameters["properties"]
    assert "spec_id" in s.parameters["properties"]


def test_parse_template_metadata():
    t = _tool_parse()
    assert t.requires_tool_context is True
    assert t.risk == RiskClass.READ


def test_fill_from_content_metadata():
    t = _tool_fill()
    assert t.requires_tool_context is True
    assert t.risk == RiskClass.WRITE_LOCAL


def test_generate_article_metadata():
    t = _tool_generate()
    assert t.requires_tool_context is True
    assert t.risk == RiskClass.WRITE_LOCAL


def test_validate_metadata():
    t = _tool_validate()
    assert t.requires_tool_context is True
    assert t.risk == RiskClass.READ


# ── parse_template behavior ──────────────────────────────────────────


def test_parse_template_missing_file_path():
    r = _tool_parse().execute(file_path="")
    assert r.success is False
    assert "content_shape_invalid" in r.error


def test_parse_template_unsupported_extension(tmp_path: Path):
    bad = tmp_path / "x.txt"
    bad.write_text("hello")
    r = _tool_parse().execute(file_path=str(bad))
    assert r.success is False
    assert "parse_failed" in r.error


def test_parse_template_happy_path(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    import shutil

    target = ws / "tmpl.docx"
    shutil.copy2(TEMPLATE_PATH, target)
    r = _tool_parse().execute(file_path=str(target))
    assert r.success is True, r.error
    spec = r.content["spec"]
    assert spec["spec_id"]
    assert spec["template_sha256"]
    assert isinstance(spec["headings"], list)
    assert abs(spec["body_pt"] - 12.0) < 0.01


# ── fill_from_content behavior ───────────────────────────────────────


def test_fill_from_content_requires_content(tmp_path: Path):
    _setup_workspace(tmp_path)
    token = set_tool_context(_ctx())
    try:
        r = _tool_fill().execute(content=None)
        assert r.success is False
        assert "content_shape_invalid" in r.error
    finally:
        reset_tool_context(token)


def test_fill_from_content_invalid_shape(tmp_path: Path):
    _setup_workspace(tmp_path)
    token = set_tool_context(_ctx())
    try:
        # title 期望 str，传 int → Pydantic ValidationError
        r = _tool_fill().execute(content={"title": 12345, "abstract": "x", "sections": {}})
        assert r.success is False
        assert "content_shape_invalid" in r.error
    finally:
        reset_tool_context(token)


def test_fill_from_content_no_workspace_binding():
    """无 ctx → workspace_not_bound（先于任何路径检查）。"""
    _clear_context()
    r = _tool_fill().execute(content=_content(), file_path=str(TEMPLATE_PATH))
    assert r.success is False
    assert "workspace_not_bound" in r.error


def test_fill_from_content_happy_path(tmp_path: Path):
    """完整流程：parse → fill，断言 gen_id + output_path 在 ws 内。"""
    ws = _setup_workspace(tmp_path)
    import shutil

    target = ws / "tmpl.docx"
    shutil.copy2(TEMPLATE_PATH, target)
    token = set_tool_context(_ctx())
    try:
        r = _tool_fill().execute(
            content=_content(),
            file_path=str(target),
            output_filename="paper.docx",
        )
        assert r.success is True, r.error
        assert r.content["gen_id"]
        assert r.content["output_path"].endswith("paper.docx")
        assert Path(r.content["output_path"]).is_file()
    finally:
        reset_tool_context(token)


# ── validate behavior ───────────────────────────────────────────────


def test_validate_missing_file_path():
    r = _tool_validate().execute(file_path="")
    assert r.success is False
    assert "content_shape_invalid" in r.error


def test_validate_no_workspace_binding():
    _clear_context()
    r = _tool_validate().execute(file_path=str(GOOD_FILLED))
    assert r.success is False
    assert "workspace_not_bound" in r.error


def test_validate_happy_path(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    import shutil

    tmpl = ws / "tmpl.docx"
    shutil.copy2(TEMPLATE_PATH, tmpl)
    filled = ws / "filled.docx"
    shutil.copy2(GOOD_FILLED, filled)
    token = set_tool_context(_ctx())
    try:
        spec_res = _tool_parse().execute(file_path=str(tmpl))
        assert spec_res.success
        spec_id = spec_res.content["spec"]["spec_id"]
        r = _tool_validate().execute(file_path=str(filled), spec_id=spec_id)
        assert r.success is True, r.error
        assert isinstance(r.content["violations"], list)
        assert "error_count" in r.content
        assert "warning_count" in r.content
    finally:
        reset_tool_context(token)


# ── generate_article behavior ────────────────────────────────────────


def test_generate_article_missing_user_request(tmp_path: Path):
    _setup_workspace(tmp_path)
    token = set_tool_context(_ctx())
    try:
        r = _tool_generate().execute(user_request="")
        assert r.success is False
        assert "content_shape_invalid" in r.error
    finally:
        reset_tool_context(token)


def test_generate_article_no_workspace_binding():
    _clear_context()
    r = _tool_generate().execute(user_request="写一篇")
    assert r.success is False
    assert "workspace_not_bound" in r.error


def test_generate_article_happy_path(tmp_path: Path):
    """完整流程：parse → generate（用 stub adapter），断言 gen_id/output_path。"""
    ws = _setup_workspace(tmp_path)
    import shutil

    tmpl = ws / "tmpl.docx"
    shutil.copy2(TEMPLATE_PATH, tmpl)
    token = set_tool_context(_ctx())
    try:
        spec_res = _tool_parse().execute(file_path=str(tmpl))
        assert spec_res.success
        spec_id = spec_res.content["spec"]["spec_id"]
        with patch(
            "backend.tools.office_journal_tool.get_default_journal_llm_adapter",
            return_value=_StubLLM(),
        ):
            r = _tool_generate().execute(
                user_request="写一篇关于 AI 的论文",
                spec_id=spec_id,
                output_filename="article.docx",
            )
        assert r.success is True, r.error
        assert r.content["gen_id"]
        assert r.content["output_path"].endswith("article.docx")
        assert Path(r.content["output_path"]).is_file()
    finally:
        reset_tool_context(token)


def test_generate_article_adapter_unavailable(tmp_path: Path):
    """adapter 工厂抛异常时 → parse_failed 错误（不静默死锁）。"""
    ws = _setup_workspace(tmp_path)
    import shutil

    tmpl = ws / "tmpl.docx"
    shutil.copy2(TEMPLATE_PATH, tmpl)
    token = set_tool_context(_ctx())
    try:
        spec_res = _tool_parse().execute(file_path=str(tmpl))
        assert spec_res.success
        spec_id = spec_res.content["spec"]["spec_id"]
        with patch(
            "backend.tools.office_journal_tool.get_default_journal_llm_adapter",
            side_effect=RuntimeError("no provider"),
        ):
            r = _tool_generate().execute(
                user_request="写一篇",
                spec_id=spec_id,
            )
        assert r.success is False
        assert "parse_failed" in r.error
    finally:
        reset_tool_context(token)
