"""M3 Word 格式转换测试：.doc ↔ .docx（LibreOffice stub）。

对应计划 docs/plans/2026-11-26_word-layout-template-p0.md M3（P0-5）。
CI 不安装真实转换器：soffice 定位与 subprocess.run 均被替身替换。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.office import word_convert


def _patch_converter(monkeypatch: pytest.MonkeyPatch, target: str = "docx"):
    calls = {}

    def fake_run(cmd, capture_output=False, check=False, timeout=None):
        calls["cmd"] = cmd
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        source = Path(cmd[-1])
        (outdir / f"{source.stem}.{target}").write_bytes(b"converted")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(word_convert, "_locate_soffice", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(word_convert.subprocess, "run", fake_run)
    return calls


def test_convert_doc_to_docx_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_converter(monkeypatch, "docx")
    source = tmp_path / "contract.doc"
    source.write_bytes(b"legacy doc")

    result = word_convert.convert_word(source, tmp_path, target_format="docx")

    assert result.ok is True
    assert result.method == "libreoffice"
    assert result.output_path is not None
    output = Path(result.output_path)
    assert output == tmp_path / "contract.docx"
    assert output.read_bytes() == b"converted"
    assert "--convert-to" in calls["cmd"]
    assert "docx" in calls["cmd"]
    assert calls["cmd"][-1] == str(source)


def test_convert_custom_output_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_converter(monkeypatch, "docx")
    source = tmp_path / "contract.doc"
    source.write_bytes(b"legacy doc")

    result = word_convert.convert_word(
        source, tmp_path, target_format="docx", output_filename="新版合同.docx"
    )

    assert result.ok is True
    assert (tmp_path / "新版合同.docx").exists()


def test_convert_without_converter_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(word_convert, "_locate_soffice", lambda: None)
    monkeypatch.setattr(sys, "platform", "linux")
    source = tmp_path / "old.doc"
    source.write_bytes(b"legacy")

    result = word_convert.convert_word(source, tmp_path, target_format="docx")

    assert result.ok is False
    assert "转换器" in (result.error or "")


def test_convert_timeout_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(word_convert, "_locate_soffice", lambda: "/usr/bin/soffice")

    def timeout_run(cmd, capture_output=False, check=False, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(word_convert.subprocess, "run", timeout_run)
    source = tmp_path / "old.doc"
    source.write_bytes(b"legacy")

    result = word_convert.convert_word(source, tmp_path, target_format="docx")

    assert result.ok is False
    assert "超时" in (result.error or "")


def test_convert_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_converter(monkeypatch, "docx")
    source = tmp_path / "old.doc"
    source.write_bytes(b"legacy")
    (tmp_path / "old.docx").write_bytes(b"existing")

    result = word_convert.convert_word(source, tmp_path, target_format="docx")

    assert result.ok is False
    assert "已存在" in (result.error or "")

    result = word_convert.convert_word(
        source, tmp_path, target_format="docx", overwrite=True
    )
    assert result.ok is True
    assert (tmp_path / "old.docx").read_bytes() == b"converted"


def test_convert_rejects_source_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_converter(monkeypatch, "docx")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.doc"
    outside.write_bytes(b"legacy")

    result = word_convert.convert_word(outside, workspace, target_format="docx")

    assert result.ok is False
    assert "工作区" in (result.error or "")


def test_convert_rejects_same_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_converter(monkeypatch, "docx")
    source = tmp_path / "doc.docx"
    source.write_bytes(b"docx")

    result = word_convert.convert_word(source, tmp_path, target_format="docx")

    assert result.ok is False
    assert "相同" in (result.error or "")


def test_convert_endpoint_delegates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api.office_word_convert_routes import (
        WordConvertRequest,
        convert_word_endpoint,
    )

    _patch_converter(monkeypatch, "docx")
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy")

    response = convert_word_endpoint(
        WordConvertRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            target_format="docx",
        )
    )

    assert response["ok"] is True
    assert response["output_path"] == str(tmp_path / "legacy.docx")
