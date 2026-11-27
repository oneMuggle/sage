"""P0 Word 格式转换 Agent 工具测试（stub 转换服务）。"""

from __future__ import annotations

from pathlib import Path

from backend.office.word_convert import WordConvertResult
from backend.tools.office_convert_tool import OfficeConvertWordTool


def test_convert_tool_rejects_relative_path() -> None:
    tool = OfficeConvertWordTool()
    result = tool.execute(file_path="relative.doc")
    assert result.success is False
    assert "absolute" in (result.error or "")


def test_convert_tool_rejects_unsupported_type(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("x")
    tool = OfficeConvertWordTool()
    result = tool.execute(file_path=str(source))
    assert result.success is False
    assert "unsupported_file_type" in (result.error or "")


def test_convert_tool_delegates_and_records_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "old.doc"
    source.write_bytes(b"legacy")
    output = tmp_path / "old.docx"
    output.write_bytes(b"converted")
    calls = {}

    def fake_convert(path, workspace, **kwargs):
        calls["path"] = path
        calls["workspace"] = workspace
        calls["kwargs"] = kwargs
        return WordConvertResult(
            ok=True,
            target_format="docx",
            method="libreoffice",
            output_path=str(output),
        )

    monkeypatch.setattr(
        "backend.tools.office_convert_tool.convert_word", fake_convert
    )

    tool = OfficeConvertWordTool()
    result = tool.execute(file_path=str(source), target_format="docx")

    assert result.success is True
    assert calls["path"] == source
    assert calls["kwargs"]["target_format"] == "docx"
    assert result.content["filename"] == "old.docx"
    assert result.content["method"] == "libreoffice"


def test_convert_tool_maps_service_error(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "old.doc"
    source.write_bytes(b"legacy")

    monkeypatch.setattr(
        "backend.tools.office_convert_tool.convert_word",
        lambda *args, **kwargs: WordConvertResult(
            ok=False, target_format="docx", error="未找到可用的转换器"
        ),
    )

    tool = OfficeConvertWordTool()
    result = tool.execute(file_path=str(source))

    assert result.success is False
    assert "转换器" in (result.error or "")
