"""P1-C (office-p1c)：旧格式 (.doc/.xls/.ppt) staging 副本就地转换。

soffice 依赖全部打桩（与 test_export_pdf 同款手法）：fake 的
subprocess.run 在 outdir 里产出真实可解析的 PyMuPDF/目标文件，
断言 ok 语义、围栏拒绝、扩展名白名单与失败契约。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from backend.office import legacy_import
from backend.office.legacy_import import LegacyImportRequest, convert_legacy_import

pytestmark = pytest.mark.unit


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _make_fake_converter(monkeypatch: pytest.MonkeyPatch, *, ok: bool = True) -> None:
    """Pin soffice 定位 + 替换 subprocess.run：在 outdir 产出目标文件。"""

    def fake_run(cmd: list, **kwargs: Any) -> subprocess.CompletedProcess:
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        target = cmd[cmd.index("--convert-to") + 1]
        (outdir / ("old." + target)).write_bytes(b"converted bytes")
        return subprocess.CompletedProcess(cmd, 0 if ok else 3, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(legacy_import, "_locate_soffice", lambda: "/fake/soffice")
    monkeypatch.setattr(legacy_import.subprocess, "run", fake_run)


def test_converts_doc_staged_copy_in_place(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_fake_converter(monkeypatch)
    staged = ws / "office" / "word" / "tok"
    staged.mkdir(parents=True)
    (staged / "old.doc").write_bytes(b"legacy bytes")

    result = convert_legacy_import(
        LegacyImportRequest(workspace_path=str(ws), file_path=str(staged / "old.doc"))
    )
    assert result.ok is True
    assert result.doc_type == "docx"
    assert result.converted_filename == "old.docx"
    converted = Path(result.converted_path or "")
    assert converted.is_file()
    assert converted.read_bytes() == b"converted bytes"
    # 旧格式原件已删除
    assert not (staged / "old.doc").exists()


def test_missing_soffice_returns_guidance(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legacy_import, "_locate_soffice", lambda: None)
    staged = ws / "old.xls"
    staged.write_bytes(b"legacy")

    result = convert_legacy_import(
        LegacyImportRequest(workspace_path=str(ws), file_path=str(staged))
    )
    assert result.ok is False
    assert "LibreOffice" in (result.error or "")


def test_rejects_workspace_escape(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_fake_converter(monkeypatch)
    outside = ws.parent / "outside.doc"
    outside.write_bytes(b"legacy")

    result = convert_legacy_import(
        LegacyImportRequest(workspace_path=str(ws), file_path=str(outside))
    )
    assert result.ok is False
    assert result.converted_path is None
    assert str(ws) not in (result.error or "")


def test_rejects_non_legacy_extension(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_fake_converter(monkeypatch)
    staged = ws / "new.docx"
    staged.write_bytes(b"pk")

    result = convert_legacy_import(
        LegacyImportRequest(workspace_path=str(ws), file_path=str(staged))
    )
    assert result.ok is False
    assert ".doc/.xls/.ppt" in (result.error or "")


def test_converter_failure_is_folded(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_fake_converter(monkeypatch, ok=False)
    staged = ws / "old.ppt"
    staged.write_bytes(b"legacy")

    result = convert_legacy_import(
        LegacyImportRequest(workspace_path=str(ws), file_path=str(staged))
    )
    assert result.ok is False
    assert "exit code 3" in (result.error or "")


def test_missing_staged_file_ok_false(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_fake_converter(monkeypatch)
    result = convert_legacy_import(
        LegacyImportRequest(workspace_path=str(ws), file_path=str(ws / "ghost.doc"))
    )
    assert result.ok is False
