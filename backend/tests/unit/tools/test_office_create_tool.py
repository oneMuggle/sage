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
    assert result.error == "unsupported_doc_type: pdf"


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

