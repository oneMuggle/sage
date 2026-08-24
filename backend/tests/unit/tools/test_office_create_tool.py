"""Unit tests for :mod:`backend.tools.office_create_tool`."""

from __future__ import annotations

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.office.excel import read_xlsx
from backend.office.models import OfficeDocType
from backend.office.word import read_docx
from backend.tools.office_create_tool import OfficeCreateTool

pytestmark = pytest.mark.unit


def _tool(**policy_kwargs) -> OfficeCreateTool:
    return OfficeCreateTool(policy=ToolPolicy(**policy_kwargs))


def _word_args(output_dir: str) -> dict:
    return {
        "doc_type": "word",
        "output_dir": output_dir,
        "filename": "天气.docx",
        "content": {"title": "天气", "paragraphs": [{"text": "今天天气很好"}]},
    }


def test_schema_requires_no_tool_context_and_exposes_fields():
    tool = _tool()
    assert tool.requires_tool_context is False
    props = tool.schema.parameters["properties"]
    assert set(props.keys()) == {"doc_type", "output_dir", "filename", "content"}
    # doc_type 合法取值必须与 models.OfficeDocType 枚举一致（单一事实来源）
    assert props["doc_type"]["enum"] == [t.value for t in OfficeDocType]


def test_create_word_to_output_dir(tmp_path):
    out_dir = tmp_path / "desktop"
    out_dir.mkdir()
    result = _tool().execute(**_word_args(str(out_dir)))
    assert result.success is True
    target = out_dir / "天气.docx"
    assert result.content["path"] == str(target)
    assert target.exists()
    parsed = read_docx(target, workspace_path="")
    # 标题以 Title 样式作为段落被提取，正文紧随其后（与 test_generate_output_dir 读语义一致）
    assert [p.text for p in parsed.paragraphs] == ["天气", "今天天气很好"]


def test_create_excel_to_output_dir(tmp_path):
    result = _tool().execute(
        doc_type="excel",
        output_dir=str(tmp_path),
        filename="data.xlsx",
        content={"sheets": [{"name": "S1", "headers": ["A"], "rows": [["1"]]}]},
    )
    assert result.success is True
    target = tmp_path / "data.xlsx"
    assert target.exists()
    parsed = read_xlsx(target, workspace_path="")
    # 第 0 行是表头，第 1 行是数据行（与 test_generate_output_dir 读语义一致）
    assert parsed.sheets[0].rows[1] == ["1"]


def test_create_ppt_to_output_dir(tmp_path):
    result = _tool().execute(
        doc_type="ppt",
        output_dir=str(tmp_path),
        filename="deck.pptx",
        content={"slides": [{"title": "标题", "bullets": ["点"]}]},
    )
    assert result.success is True
    assert (tmp_path / "deck.pptx").exists()


def test_rejects_existing_target_file(tmp_path):
    target = tmp_path / "天气.docx"
    target.write_text("occupied")
    result = _tool().execute(**_word_args(str(tmp_path)))
    assert result.success is False
    assert result.error.startswith("file_exists")


def test_rejects_output_dir_that_is_a_file(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    result = _tool().execute(**{**_word_args(str(blocker)), "filename": "a.docx"})
    assert result.success is False
    assert result.error == "output_dir_not_directory"


def test_rejects_unsupported_doc_type(tmp_path):
    result = _tool().execute(doc_type="pdf", output_dir=str(tmp_path), filename="a.pdf", content={})
    assert result.success is False


def test_accepts_uppercase_doc_type(tmp_path):
    """doc_type 大小写容错：Word/WORD → word（T6 实测模型传大写）。"""
    result = _tool().execute(
        doc_type="Word",
        output_dir=str(tmp_path),
        filename="a.docx",
        content={"title": "t", "paragraphs": [{"text": "hi"}]},
    )
    assert result.success is True
    assert (tmp_path / "a.docx").exists()


def test_word_content_as_plain_text(tmp_path):
    """content 纯字符串 → 自动包装为 Word 正文段落（"写入一句话"场景）。"""
    result = _tool().execute(
        doc_type="word",
        output_dir=str(tmp_path),
        filename="天气.docx",
        content="今天天气很好",
    )
    assert result.success is True
    target = tmp_path / "天气.docx"
    assert target.exists()
    parsed = read_docx(target, workspace_path="")
    assert any(p.text == "今天天气很好" for p in parsed.paragraphs)


def test_excel_content_plain_text_still_rejected(tmp_path):
    """excel 不接受纯文本 content（需 sheets 结构）——保持严格。"""
    result = _tool().execute(
        doc_type="excel", output_dir=str(tmp_path), filename="a.xlsx", content="today"
    )
    assert result.success is False


def test_schema_content_declares_nested_structure():
    """content 的 JSON Schema 应内联声明 word/excel/ppt 的嵌套结构。"""
    tool = _tool()
    content_props = tool.schema.parameters["properties"]["content"]["properties"]
    assert "title" in content_props
    assert "paragraphs" in content_props
    assert "tables" in content_props
    assert "sheets" in content_props
    assert "slides" in content_props


def test_rejects_relative_output_dir(tmp_path):
    """相对路径 output_dir（"Desktop"）应拒绝——避免静默写到 cwd 而非真实桌面。

    T6 实测：LLM 传 output_dir="Desktop"，工具 resolve 到 <cwd>/Desktop 而非
    ~/Desktop。明确错误提示让 LLM 重试用 ~/Desktop / 绝对路径。
    """
    result = _tool().execute(
        doc_type="word",
        output_dir="Desktop",
        filename="a.docx",
        content={"title": "t", "paragraphs": [{"text": "hi"}]},
    )
    assert result.success is False
    assert result.error.startswith("output_dir_relative")


def test_output_dir_required():
    result = _tool().execute(
        doc_type="word", output_dir=None, filename="a.docx",
        content={"title": "t", "paragraphs": []},
    )
    assert result.success is False
    assert result.error == "output_dir_required"


def test_filename_required(tmp_path):
    result = _tool().execute(
        doc_type="word", output_dir=str(tmp_path), filename="  ",
        content={"title": "t", "paragraphs": []},
    )
    assert result.success is False
    assert result.error == "filename_required"


def test_content_required(tmp_path):
    result = _tool().execute(
        doc_type="word", output_dir=str(tmp_path), filename="a.docx", content={},
    )
    assert result.success is False
    assert result.error == "content_required"


def test_rejects_output_dir_outside_workspace_when_bound(tmp_path, tmp_path_factory):
    workspace = tmp_path
    outside = tmp_path_factory.mktemp("outside")
    result = _tool(workspace_root=str(workspace)).execute(
        doc_type="word",
        output_dir=str(outside),
        filename="a.docx",
        content={"title": "t", "paragraphs": [{"text": "x"}]},
    )
    assert result.success is False
    assert "path_outside_workspace" in result.error
    assert not (outside / "a.docx").exists()


def test_allows_output_dir_inside_workspace_when_bound(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = _tool(workspace_root=str(workspace)).execute(
        doc_type="word",
        output_dir=str(workspace),
        filename="b.docx",
        content={"title": "t", "paragraphs": [{"text": "x"}]},
    )
    assert result.success is True
    assert (workspace / "b.docx").exists()


# ──────────────────────────────────────────────────────────────────────
# Binding-aware create (T7.5 round-trip fix)
#
# When ``ToolExecutionContext`` carries a live ``session_id`` AND that
# session has an active workspace binding, the tool must:
#   1. Delegate to ``OfficeToolService.create`` so the document is
#      registered in ``office_documents`` (otherwise list/read can't see it).
#   2. Drop the absolute ``workspace_path`` from the result payload.
#   3. Keep the existing ``output_dir`` flow for the unbound (legacy)
#      case — i.e. plain "create on my Desktop" still works without a
#      binding.
# ──────────────────────────────────────────────────────────────────────


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _ctx(session_id: str, binding_generation: int) -> "ToolExecutionContext":
    from backend.tools.context import ToolExecutionContext

    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-x",
        binding_generation=binding_generation,
        office_doc_scope=frozenset(),
    )


def test_create_with_session_binding_registers_document(tmp_path, monkeypatch):
    """When a session binding is active, ``office_create`` must delegate to
    ``OfficeToolService.create`` so the doc is registered for list/read.

    Without this delegation the file lands on disk but is invisible to the
    rest of the Office scope — the round-trip bug T7.5 fixes.
    """
    from backend.data.database import Database
    from backend.office.session_workspace import bind_session_workspace
    from backend.tools.context import reset_tool_context, set_tool_context

    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-bound")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-bound", str(work), now_ms=1)

    # Capture the call site — proves we delegated instead of writing raw.
    delegated: list = []
    real_svc_create = "backend.office.tool_service.OfficeToolService.create"

    def _spy_create(self, _conn, session_id_arg, generation_arg, **_kwargs):
        delegated.append((session_id_arg, generation_arg))
        return {
            "success": True,
            "content": {
                "document_id": "stub-id",
                "doc_type": "word",
                "filename": "天气.docx",
            },
        }

    monkeypatch.setattr(real_svc_create, _spy_create, raising=False)
    monkeypatch.setattr("backend.tools.office_create_tool.get_database", lambda: db)

    ctx = _ctx("sess-bound", binding.generation)
    token = set_tool_context(ctx)
    try:
        result = _tool().execute(**_word_args(str(work)))
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content == {
        "document_id": "stub-id",
        "doc_type": "word",
        "filename": "天气.docx",
    }
    assert delegated == [("sess-bound", binding.generation)]


def test_create_with_binding_does_not_leak_workspace_path(tmp_path, monkeypatch):
    """The tool result must NOT echo the binding's absolute workspace path.

    Symmetric with the office_list / office_read "no path leak" invariant.
    Tool-generated docs are first-class Office scope items; their handle is
    ``{document_id, doc_type, filename}``.
    """
    from backend.data.database import Database
    from backend.office.session_workspace import bind_session_workspace
    from backend.tools.context import reset_tool_context, set_tool_context

    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-bound")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-bound", str(work), now_ms=1)

    def _fake_create(self, _conn, session_id_arg, generation_arg, **_kwargs):
        return {
            "success": True,
            "content": {
                "document_id": "stub-id",
                "doc_type": "word",
                "filename": "天气.docx",
            },
        }

    real_svc_create = "backend.office.tool_service.OfficeToolService.create"
    monkeypatch.setattr(real_svc_create, _fake_create, raising=False)
    monkeypatch.setattr("backend.tools.office_create_tool.get_database", lambda: db)

    ctx = _ctx("sess-bound", binding.generation)
    token = set_tool_context(ctx)
    try:
        result = _tool().execute(**_word_args(str(work)))
    finally:
        reset_tool_context(token)

    import json

    full_text = json.dumps(result.content, ensure_ascii=False)
    assert str(work.resolve()) not in full_text


def test_create_without_binding_keeps_legacy_output_dir_behavior(tmp_path):
    """Without a session binding the tool must keep writing to ``output_dir``
    and return the legacy ``{path, filename, bytes}`` shape.

    Plain "create a doc on my Desktop" requests still hit this path — it's
    the most common case for users who never opened a workspace. Breaking
    it would silently regress the existing happy path.
    """
    from backend.tools.context import reset_tool_context, set_tool_context

    out_dir = tmp_path / "desktop"
    out_dir.mkdir()

    ctx = _ctx("sess-no-binding", binding_generation=0)
    token = set_tool_context(ctx)
    try:
        result = _tool().execute(**_word_args(str(out_dir)))
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert set(result.content.keys()) == {"path", "filename", "bytes"}
    assert (out_dir / "天气.docx").exists()

