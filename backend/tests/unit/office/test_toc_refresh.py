"""Unit tests for backend.office.toc_refresh (Round 39 — 目录真页码).

CI 无 Windows Word：Word COM 分支经注入 ``sys.modules`` 的 stub
``win32com`` / ``pythoncom`` 模块驱动（镜像 test_export_pdf 的假转换器
手法），记录 Open/Update/Save/Close/Quit 调用序列供断言。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from backend.office.toc_refresh import (
    TocRefreshResult,
    refresh_toc_page_numbers,
    word_com_applicable,
)

# ──────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    """A fresh workspace directory per test."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _make_source(workspace: Path, name: str = "report.docx") -> Path:
    source = workspace / name
    source.write_bytes(b"PK\x03\x04 fake docx")
    return source


def _install_com_stubs(
    monkeypatch: pytest.MonkeyPatch,
    recorder: Dict[str, Any],
    *,
    toc_count: int = 2,
    fail_on_update_index: Optional[int] = None,
    fail_on_open: bool = False,
) -> None:
    """Inject stub pythoncom + win32com that record the COM call sequence."""

    class _FakeToc:
        def __init__(self, index: int) -> None:
            self.index = index

        def Update(self) -> None:  # noqa: N802 — COM API name
            updates: List[int] = recorder.setdefault("updated", [])
            if fail_on_update_index is not None and self.index == fail_on_update_index:
                raise RuntimeError("update boom")
            updates.append(self.index)

    class _FakeTocs:
        Count = toc_count  # noqa: N815 — COM API name

        def Item(self, i: int) -> _FakeToc:  # noqa: N802, N803 — COM API name
            recorder.setdefault("items", []).append(i)
            return _FakeToc(i)

    class _FakeDocument:
        def Save(self) -> None:  # noqa: N802 — COM API name
            recorder["saved"] = True

        def Close(self, **kwargs: Any) -> None:  # noqa: N802 — COM API name
            recorder["closed"] = kwargs

        TablesOfContents = _FakeTocs()  # noqa: N815 — COM API name

    class _FakeDocuments:
        def Open(self, FileName, **kwargs):  # noqa: N802, N803 — COM API names
            if fail_on_open:
                raise RuntimeError("open boom")
            recorder["opened"] = (FileName, kwargs)
            return _FakeDocument()

    class _FakeWord:
        def __init__(self) -> None:
            self.Visible = None
            self.DisplayAlerts = None
            self.AutomationSecurity = None
            self.Documents = _FakeDocuments()

        def Quit(self) -> None:  # noqa: N802 — COM API name
            recorder["quit"] = True

    def fake_dispatch(prog_id: str) -> _FakeWord:
        recorder["prog_id"] = prog_id
        return _FakeWord()

    client_mod = types.ModuleType("win32com.client")
    client_mod.DispatchEx = fake_dispatch  # type: ignore[attr-defined]
    win32com_mod = types.ModuleType("win32com")
    win32com_mod.client = client_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32com", win32com_mod)
    monkeypatch.setitem(sys.modules, "win32com.client", client_mod)

    pythoncom_mod = types.ModuleType("pythoncom")
    pythoncom_mod.CoInitialize = (  # type: ignore[attr-defined]
        lambda: recorder.setdefault("co_init", []).append(True)
    )
    pythoncom_mod.CoUninitialize = (  # type: ignore[attr-defined]
        lambda: recorder.setdefault("co_uninit", []).append(True)
    )
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom_mod)


# ──────────────────────────────────────────────────────────────────────
# Success / no-op paths
# ──────────────────────────────────────────────────────────────────────


def test_refresh_updates_all_tocs_and_saves(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    source = _make_source(ws)
    recorder: Dict[str, Any] = {}
    _install_com_stubs(monkeypatch, recorder, toc_count=2)

    result = refresh_toc_page_numbers(source, ws)

    assert result.ok is True
    assert result.toc_count == 2
    assert result.error is None
    assert result.method == "word_com"
    assert recorder["updated"] == [1, 2]
    assert recorder["saved"] is True
    assert recorder["closed"] == {"SaveChanges": False}
    assert recorder["quit"] is True
    # COM 生命周期：独立实例 + 禁告警 + 强制禁宏 + 可写打开 + 线程初始化配平。
    assert recorder["prog_id"] == "Word.Application"
    assert recorder["co_init"] == [True]
    assert recorder["co_uninit"] == [True]
    file_name, open_kwargs = recorder["opened"]
    assert Path(file_name).resolve() == source.resolve()
    assert open_kwargs.get("ReadOnly") is False


def test_refresh_no_toc_is_successful_noop(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    """文档没有目录 → ok=True / toc_count=0，不落盘（不 Save）。"""
    source = _make_source(ws)
    recorder: Dict[str, Any] = {}
    _install_com_stubs(monkeypatch, recorder, toc_count=0)

    result = refresh_toc_page_numbers(source, ws)

    assert result.ok is True
    assert result.toc_count == 0
    assert "saved" not in recorder
    assert recorder["quit"] is True


# ──────────────────────────────────────────────────────────────────────
# Degradation paths (never raises)
# ──────────────────────────────────────────────────────────────────────


def test_refresh_without_pywin32_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    """pywin32 缺失 → ok=False 带安装引导文案（绝不抛异常）。"""
    source = _make_source(ws)
    monkeypatch.setitem(sys.modules, "pythoncom", None)
    monkeypatch.setitem(sys.modules, "win32com", None)
    monkeypatch.setitem(sys.modules, "win32com.client", None)

    result = refresh_toc_page_numbers(source, ws)

    assert result.ok is False
    assert result.toc_count == 0
    assert result.error is not None
    assert "pywin32" in result.error
    assert "pip install pywin32" in result.error
    assert "F9" in result.error


def test_refresh_com_failure_still_closes_and_quits(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    """Update 中途抛错 → ok=False，finally 仍 Close/Quit 不泄漏进程。"""
    source = _make_source(ws)
    recorder: Dict[str, Any] = {}
    _install_com_stubs(monkeypatch, recorder, toc_count=3, fail_on_update_index=2)

    result = refresh_toc_page_numbers(source, ws)

    assert result.ok is False
    assert "Word COM 目录刷新失败" in (result.error or "")
    assert recorder["updated"] == [1]
    assert recorder["closed"] == {"SaveChanges": False}
    assert recorder["quit"] is True
    assert recorder["co_uninit"] == [True]


def test_refresh_open_failure_still_quits(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    source = _make_source(ws)
    recorder: Dict[str, Any] = {}
    _install_com_stubs(monkeypatch, recorder, fail_on_open=True)

    result = refresh_toc_page_numbers(source, ws)

    assert result.ok is False
    assert recorder["quit"] is True
    assert "closed" not in recorder


# ──────────────────────────────────────────────────────────────────────
# Path fence
# ──────────────────────────────────────────────────────────────────────


def test_rejects_non_docx_suffix(ws: Path) -> None:
    source = ws / "report.txt"
    source.write_text("not a docx")

    result = refresh_toc_page_numbers(source, ws)

    assert result.ok is False
    assert "仅支持 .docx" in (result.error or "")


def test_rejects_missing_file(ws: Path) -> None:
    result = refresh_toc_page_numbers(ws / "missing.docx", ws)

    assert result.ok is False
    assert "源文件不存在" in (result.error or "")


def test_rejects_source_outside_workspace(tmp_path: Path, ws: Path) -> None:
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"PK\x03\x04")

    result = refresh_toc_page_numbers(outside, ws)

    assert result.ok is False
    assert "不在 workspace 内" in (result.error or "")


def test_rejects_invalid_workspace(tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"PK\x03\x04")

    result = refresh_toc_page_numbers(source, tmp_path / "no-such-workspace")

    assert result.ok is False
    assert "workspace 无效" in (result.error or "")


# ──────────────────────────────────────────────────────────────────────
# Platform gate
# ──────────────────────────────────────────────────────────────────────


def test_word_com_applicable_reports_platform() -> None:
    applicable, reason = word_com_applicable()
    if sys.platform == "win32":
        assert applicable is True
        assert reason == ""
    else:
        assert applicable is False
        assert "Windows" in reason


def test_result_model_forbids_extra_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TocRefreshResult(ok=True, toc_count=1, unexpected="x")  # type: ignore[call-arg]
