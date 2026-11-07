from __future__ import annotations

import pytest

from backend.office.generate_service import (
    build_nl_prompt,
    next_iteration_filename,
    parse_llm_spec,
    to_excel_request,
    to_pdf_request,
    to_ppt_request,
    to_word_request,
)


def test_build_nl_prompt_word() -> None:
    prompt = build_nl_prompt(
        instruction="写一份项目周报",
        doc_type="word",
        reference_texts=["上周完成了功能A"],
    )
    assert "项目周报" in prompt
    assert "word" in prompt
    assert "上周完成了功能A" in prompt


def test_build_nl_prompt_no_reference() -> None:
    prompt = build_nl_prompt(instruction="写一份PPT", doc_type="ppt")
    assert "PPT" in prompt
    assert "ppt" in prompt


def test_build_nl_prompt_names_kind_specific_key() -> None:
    assert "slides" in build_nl_prompt(instruction="x", doc_type="ppt")
    assert "sheets" in build_nl_prompt(instruction="x", doc_type="excel")
    assert "pages" in build_nl_prompt(instruction="x", doc_type="pdf")
    assert "paragraphs" in build_nl_prompt(instruction="x", doc_type="word")


def test_parse_llm_spec_valid_word() -> None:
    llm_output = """
{
  "title": "项目周报",
  "paragraphs": [
    {"heading": "h1", "text": "概述"},
    {"text": "本周完成了功能A。"}
  ]
}
"""
    spec = parse_llm_spec(llm_output, doc_type="word")
    assert spec["kind"] == "word"
    assert spec["title"] == "项目周报"
    assert len(spec["paragraphs"]) == 2
    assert spec["paragraphs"][0]["heading"] == "h1"


def test_parse_llm_spec_strips_json_fence() -> None:
    spec = parse_llm_spec(
        '```json\n{"title": "T", "paragraphs": [{"text": "body"}]}\n```',
        doc_type="word",
    )
    assert spec["title"] == "T"


def test_parse_llm_spec_invalid_json() -> None:
    with pytest.raises(ValueError, match="Failed to parse LLM output"):
        parse_llm_spec("not json", doc_type="word")


def test_parse_llm_spec_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_llm_spec("[1, 2, 3]", doc_type="word")


def test_parse_llm_spec_rejects_unknown_doc_type() -> None:
    with pytest.raises(ValueError, match="Unsupported doc_type"):
        parse_llm_spec('{"title": "T", "paragraphs": [{"text": "b"}]}', doc_type="markdown")


def test_parse_llm_spec_rejects_missing_word_title() -> None:
    with pytest.raises(ValueError, match="missing 'title'"):
        parse_llm_spec('{"paragraphs": [{"text": "b"}]}', doc_type="word")


@pytest.mark.parametrize(
    ("doc_type", "payload"),
    [
        ("word", '{"title": "T", "paragraphs": []}'),
        ("ppt", '{"slides": []}'),
        ("excel", '{"sheets": []}'),
        ("pdf", '{"pages": []}'),
    ],
)
def test_parse_llm_spec_rejects_empty_payload(doc_type: str, payload: str) -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_llm_spec(payload, doc_type=doc_type)


def test_to_word_request() -> None:
    spec = parse_llm_spec(
        '{"title": "Test", "paragraphs": [{"text": "Hello"}]}',
        doc_type="word",
    )
    req = to_word_request(spec, workspace_path="/tmp/ws", filename="out.docx")
    assert req.filename == "out.docx"
    assert req.title == "Test"
    assert len(req.paragraphs) == 1
    assert req.paragraphs[0].text == "Hello"


def test_to_ppt_request() -> None:
    spec = parse_llm_spec('{"slides": [{"title": "封面", "bullets": ["A"]}]}', doc_type="ppt")
    req = to_ppt_request(spec, workspace_path="/tmp/ws", filename="deck.pptx")
    assert req.filename == "deck.pptx"
    assert len(req.slides) == 1
    assert req.slides[0].title == "封面"


def test_to_excel_request() -> None:
    spec = parse_llm_spec(
        '{"sheets": [{"name": "Sheet1", "headers": ["A"], "rows": [["1"]]}]}',
        doc_type="excel",
    )
    req = to_excel_request(spec, workspace_path="/tmp/ws", filename="book.xlsx")
    assert req.filename == "book.xlsx"
    assert req.sheets[0].name == "Sheet1"


def test_to_pdf_request() -> None:
    spec = parse_llm_spec('{"pages": [{"title": "P1", "paragraphs": ["hello"]}]}', doc_type="pdf")
    req = to_pdf_request(spec, workspace_path="/tmp/ws", filename="doc.pdf")
    assert req.filename == "doc.pdf"
    assert req.pages[0].paragraphs == ["hello"]


def test_next_iteration_filename() -> None:
    assert next_iteration_filename("report.docx") == "report_v2.docx"
    assert next_iteration_filename("report_v2.docx") == "report_v3.docx"
    assert next_iteration_filename("report_v10.pptx") == "report_v11.pptx"
