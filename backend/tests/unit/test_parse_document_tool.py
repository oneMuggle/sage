from __future__ import annotations

from backend.domain.document_parse import ParseRequest, ParseResult
from backend.tools.parse_document_tool import ParseDocumentTool, _run_async


def test_schema_contract() -> None:
    schema = ParseDocumentTool().schema
    assert schema.name == "parse_document"
    assert "intranet" in schema.description.lower()
    props = schema.parameters["properties"]
    assert props["engine"]["enum"] == ["auto", "local", "mineru"]
    assert props["output_format"]["enum"] == ["markdown", "structured", "docx", "html"]


def test_run_async_bridge_from_sync_context() -> None:
    async def add(a, b):
        return a + b

    assert _run_async(add(1, 2)) == 3


def test_execute_requires_source() -> None:
    result = ParseDocumentTool().execute()
    assert result.success is False
    assert result.error == "path_or_media_id_required"


def test_execute_uses_service(monkeypatch) -> None:
    class FakeService:
        async def parse(self, request: ParseRequest) -> ParseResult:
            return ParseResult(text="parsed", engine_used="local", duration_ms=3)

    import backend.tools.parse_document_tool as mod

    monkeypatch.setattr(mod, "get_document_parse_service", lambda: FakeService())
    monkeypatch.setattr(
        mod, "read_source_bytes", lambda path, media_id: ("a.pdf", b"%PDF")
    )
    result = ParseDocumentTool().execute(media_id="m1")
    assert result.success is True
    assert result.content == "parsed"
    assert result.output["engine_used"] == "local"
