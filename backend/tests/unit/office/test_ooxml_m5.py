"""Unit tests for M5 OOXML archive/validate/run-coalescing helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from backend.office.errors import OfficeParseError
from backend.office.ooxml import (
    OoxmlMergeRunsRequest,
    OoxmlValidateRequest,
    merge_docx_runs,
    pack_ooxml,
    unpack_ooxml,
    validate_ooxml,
)


def _docx(path: Path, *, bold_second: bool = False) -> Path:
    from docx import Document

    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("Hello")
    second = paragraph.add_run(" ")
    paragraph.add_run("world")
    if bold_second:
        second.bold = True
    document.save(str(path))
    return path


def _minimal_ooxml(path: Path, document_xml: str) -> Path:
    with zipfile.ZipFile(str(path), "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
        archive.writestr("word/document.xml", document_xml)
    return path


def _read_part(path: Path, part: str) -> str:
    with zipfile.ZipFile(str(path)) as archive:
        return archive.read(part).decode("utf-8")


def test_unpack_pack_roundtrip(tmp_path: Path) -> None:
    source = _docx(tmp_path / "doc.docx")
    unpacked = tmp_path / "unpacked"

    count = unpack_ooxml(source, unpacked)
    assert count > 0
    assert (unpacked / "word" / "document.xml").is_file()

    packed = tmp_path / "packed.docx"
    pack_ooxml(unpacked, packed)
    from docx import Document

    assert Document(str(packed)).paragraphs[0].text == "Hello world"


def test_unpack_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "evil.docx"
    with zipfile.ZipFile(str(archive), "w") as handle:
        handle.writestr("../evil.xml", "<x/>")

    with pytest.raises(OfficeParseError):
        unpack_ooxml(archive, tmp_path / "out")


def test_unpack_rejects_symlink_member(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.docx"
    with zipfile.ZipFile(str(archive), "w") as handle:
        info = zipfile.ZipInfo("link")
        info.external_attr = 0o120777 << 16
        handle.writestr(info, "/etc/passwd")

    with pytest.raises(OfficeParseError):
        unpack_ooxml(archive, tmp_path / "out")


def test_validate_accepts_normal_docx(tmp_path: Path) -> None:
    source = _docx(tmp_path / "doc.docx")

    result = validate_ooxml(
        OoxmlValidateRequest(workspace_path=str(tmp_path), file_path=str(source))
    )

    assert result.valid is True
    assert result.ok is True
    assert result.issues == []


def test_validate_flags_missing_required_part(tmp_path: Path) -> None:
    source = _minimal_ooxml(
        tmp_path / "broken.docx",
        '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
    )
    rebuilt = tmp_path / "missing.docx"
    with zipfile.ZipFile(str(source)) as src, zipfile.ZipFile(str(rebuilt), "w") as dst:
        for info in src.infolist():
            if info.filename != "word/document.xml":
                dst.writestr(info, src.read(info))

    result = validate_ooxml(
        OoxmlValidateRequest(workspace_path=str(tmp_path), file_path=str(rebuilt))
    )

    assert result.valid is False
    assert any(issue.code == "required_part_missing" for issue in result.issues)


def test_validate_rejects_doctype(tmp_path: Path) -> None:
    source = _minimal_ooxml(
        tmp_path / "dtd.docx",
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
    )

    result = validate_ooxml(
        OoxmlValidateRequest(workspace_path=str(tmp_path), file_path=str(source))
    )

    assert result.valid is False
    assert any(issue.code == "xml_doctype_forbidden" for issue in result.issues)


def test_validate_repairs_missing_xml_space(tmp_path: Path) -> None:
    source = _minimal_ooxml(
        tmp_path / "space.docx",
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t> hello </w:t></w:r></w:p></w:body></w:document>",
    )

    result = validate_ooxml(
        OoxmlValidateRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            auto_repair=True,
        )
    )

    assert result.valid is True
    assert any(issue.code == "xml_space_missing" for issue in result.issues)
    assert result.repaired is True
    assert result.repaired_path
    repaired = tmp_path / result.repaired_path
    assert 'xml:space="preserve"' in _read_part(repaired, "word/document.xml")


def test_merge_docx_runs_coalesces_same_formatting(tmp_path: Path) -> None:
    source = _docx(tmp_path / "doc.docx")

    result = merge_docx_runs(
        OoxmlMergeRunsRequest(workspace_path=str(tmp_path), file_path=str(source))
    )

    assert result.merged_runs == 2
    from docx import Document

    document = Document(str(tmp_path / result.output_path))
    assert document.paragraphs[0].text == "Hello world"
    assert len(document.paragraphs[0].runs) == 1


def test_merge_docx_runs_keeps_different_formatting(tmp_path: Path) -> None:
    source = _docx(tmp_path / "doc.docx", bold_second=True)

    result = merge_docx_runs(
        OoxmlMergeRunsRequest(workspace_path=str(tmp_path), file_path=str(source))
    )

    assert result.merged_runs == 0
    from docx import Document

    assert len(Document(str(tmp_path / result.output_path)).paragraphs[0].runs) == 3


def test_merge_docx_runs_rejects_non_docx(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("text", encoding="utf-8")

    with pytest.raises(OfficeParseError):
        merge_docx_runs(
            OoxmlMergeRunsRequest(workspace_path=str(tmp_path), file_path=str(source))
        )
