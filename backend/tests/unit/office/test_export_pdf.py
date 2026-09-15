"""Unit tests for backend.office.export_pdf (item 2.7 — PDF export).

No real converter exists in CI: soffice discovery and ``subprocess.run``
are monkeypatched, and the Word COM branch is exercised through a stub
``win32com`` module injected into ``sys.modules``. The fake converter
"writes" the expected ``<stem>.pdf`` so success-path parsing can be
asserted end-to-end.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from backend.office import export_pdf
from backend.office.export_pdf import ExportPdfResult, export_to_pdf
from backend.office.path_safety import is_within

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
    source.write_bytes(b"PK\x03\x04 fake office document")
    return source


def _patch_soffice(monkeypatch: pytest.MonkeyPatch, soffice: Optional[str]) -> None:
    """Pin soffice discovery so host-installed LibreOffice can't interfere."""
    monkeypatch.setattr(export_pdf, "_locate_soffice", lambda: soffice)


def _fake_subprocess_run(
    monkeypatch: pytest.MonkeyPatch,
    captured: Dict[str, Any],
    *,
    returncode: int = 0,
    write_output: bool = True,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> None:
    """Replace subprocess.run with a fake soffice run.

    The fake records cmd/kwargs and, unless ``write_output`` is False,
    creates the expected ``<stem>.pdf`` next to the source it was given —
    simulating a successful conversion.
    """

    def fake_run(cmd: list, **kwargs: Any) -> subprocess.CompletedProcess:
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        if write_output:
            outdir = Path(cmd[cmd.index("--outdir") + 1])
            (outdir / (Path(cmd[-1]).stem + ".pdf")).write_bytes(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(export_pdf.subprocess, "run", fake_run)


def _install_win32com_stub(
    monkeypatch: pytest.MonkeyPatch,
    recorder: Dict[str, Any],
) -> None:
    """Inject a stub win32com package that records the COM calls made."""

    class _FakeDocument:
        def SaveAs2(self, FileName, FileFormat=None):  # noqa: N802, N803 — COM API names
            recorder["saveas2"] = (FileName, FileFormat)
            Path(FileName).write_bytes(b"%PDF-1.4 fake-from-word")

        def Close(self, **kwargs: Any) -> None:  # noqa: N802 — COM API name
            recorder["closed"] = kwargs

    class _FakeDocuments:
        def Open(self, FileName, **kwargs):  # noqa: N802, N803 — COM API names
            recorder["opened"] = (FileName, kwargs)
            return _FakeDocument()

    class _FakeWord:
        def __init__(self) -> None:
            self.Visible = None
            self.DisplayAlerts = None
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


# ──────────────────────────────────────────────────────────────────────
# soffice detection order: env var → shutil.which → well-known paths
# ──────────────────────────────────────────────────────────────────────


def test_locate_soffice_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """SAGE_SOFFICE_PATH has top priority over shutil.which."""
    fake = tmp_path / "custom-soffice.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("SAGE_SOFFICE_PATH", str(fake))
    monkeypatch.setattr(export_pdf.shutil, "which", lambda name: str(tmp_path / "from-path"))

    assert export_pdf._locate_soffice() == str(fake)


def test_locate_soffice_env_var_missing_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale SAGE_SOFFICE_PATH must not abort detection."""
    monkeypatch.setenv("SAGE_SOFFICE_PATH", str(tmp_path / "missing" / "soffice.exe"))
    which_calls: list = []
    monkeypatch.setattr(
        export_pdf.shutil,
        "which",
        lambda name: which_calls.append(name) or None,
    )
    monkeypatch.setattr(Path, "exists", lambda self: False)

    assert export_pdf._locate_soffice() is None
    assert which_calls == ["soffice"]


def test_locate_soffice_which_hit_skips_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A PATH hit short-circuits before the well-known-path probing."""
    monkeypatch.delenv("SAGE_SOFFICE_PATH", raising=False)
    from_path = str(tmp_path / "soffice-on-path")
    monkeypatch.setattr(export_pdf.shutil, "which", lambda name: from_path)
    # All well-known candidates "missing" — proving they're never consulted.
    monkeypatch.setattr(Path, "exists", lambda self: False)

    assert export_pdf._locate_soffice() == from_path


def test_locate_soffice_wellknown_path_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without env var and PATH, the first existing well-known path wins."""
    monkeypatch.delenv("SAGE_SOFFICE_PATH", raising=False)
    monkeypatch.setattr(export_pdf.shutil, "which", lambda name: None)
    target = export_pdf._candidate_soffice_paths()[0]
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == target)

    assert export_pdf._locate_soffice() == target


def test_locate_soffice_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var, no PATH hit, no well-known file → None (not an error)."""
    monkeypatch.delenv("SAGE_SOFFICE_PATH", raising=False)
    monkeypatch.setattr(export_pdf.shutil, "which", lambda name: None)
    monkeypatch.setattr(Path, "exists", lambda self: False)

    assert export_pdf._locate_soffice() is None


# ──────────────────────────────────────────────────────────────────────
# LibreOffice run path: argv shape, timeout, capture, output handling
# ──────────────────────────────────────────────────────────────────────


def test_export_success_via_libreoffice(monkeypatch: pytest.MonkeyPatch, ws: Path) -> None:
    source = _make_source(ws)
    fake_soffice = str(ws / "_fake" / "soffice.exe")
    captured: Dict[str, Any] = {}
    _patch_soffice(monkeypatch, fake_soffice)
    _fake_subprocess_run(monkeypatch, captured)

    result = export_to_pdf(source, ws, timeout_seconds=77)

    assert isinstance(result, ExportPdfResult)
    assert result.ok is True
    assert result.method == "libreoffice"
    assert result.error is None

    expected_pdf = source.with_suffix(".pdf").resolve()
    assert result.output_path == str(expected_pdf)
    assert expected_pdf.read_bytes().startswith(b"%PDF")
    # Output stays inside the workspace.
    assert is_within(ws.resolve(), Path(result.output_path))

    # argv list correctness.
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[0] == fake_soffice
    assert cmd[1:5] == ["--headless", "--norestore", "--convert-to", "pdf"]
    assert cmd[5] == "--outdir"
    assert Path(cmd[6]) == ws.resolve()
    assert cmd[-1] == str(source.resolve())
    assert len(cmd) == 8

    # subprocess hygiene: timeout propagated, capture on, no shell.
    kwargs = captured["kwargs"]
    assert kwargs["timeout"] == 77
    assert kwargs["capture_output"] is True
    assert kwargs.get("shell", False) is False


def test_export_overwrites_existing_pdf(monkeypatch: pytest.MonkeyPatch, ws: Path) -> None:
    """Export is an explicit action — an existing <stem>.pdf is replaced."""
    source = _make_source(ws)
    (ws / "report.pdf").write_bytes(b"OLD")

    captured: Dict[str, Any] = {}
    _patch_soffice(monkeypatch, "soffice")
    _fake_subprocess_run(monkeypatch, captured, stdout=b"ok", stderr=b"")

    result = export_to_pdf(source, ws)

    assert result.ok is True
    assert (ws / "report.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_export_timeout_reports_failure(monkeypatch: pytest.MonkeyPatch, ws: Path) -> None:
    """subprocess.TimeoutExpired → ok=False, error mentions the timeout."""
    source = _make_source(ws)

    def fake_run(cmd: list, **kwargs: Any) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(export_pdf, "_locate_soffice", lambda: "soffice")
    monkeypatch.setattr(export_pdf.subprocess, "run", fake_run)

    result = export_to_pdf(source, ws, timeout_seconds=5)

    assert result.ok is False
    assert result.method is None
    assert result.output_path is None
    error = result.error or ""
    assert "超时" in error or "timeout" in error.lower()


def test_export_nonzero_exit_includes_stderr_tail(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    source = _make_source(ws)
    captured: Dict[str, Any] = {}
    _patch_soffice(monkeypatch, "soffice")
    _fake_subprocess_run(
        monkeypatch,
        captured,
        returncode=1,
        write_output=False,
        stderr=b"Error: source could not be loaded",
    )

    result = export_to_pdf(source, ws)

    assert result.ok is False
    assert result.method is None
    assert "exit code 1" in (result.error or "")
    assert "source could not be loaded" in (result.error or "")


def test_export_success_without_output_file_fails(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    """rc=0 but no <stem>.pdf produced → failure, not a bogus success."""
    source = _make_source(ws)
    captured: Dict[str, Any] = {}
    _patch_soffice(monkeypatch, "soffice")
    _fake_subprocess_run(monkeypatch, captured, write_output=False)

    result = export_to_pdf(source, ws)

    assert result.ok is False
    assert "未找到输出 PDF" in (result.error or "")


# ──────────────────────────────────────────────────────────────────────
# Input validation: extension, existence, workspace containment
# ──────────────────────────────────────────────────────────────────────


def test_export_unsupported_extension(ws: Path) -> None:
    source = ws / "notes.txt"
    source.write_text("hello")

    result = export_to_pdf(source, ws)

    assert result.ok is False
    assert result.method is None
    assert "'.txt'" in (result.error or "")


def test_export_missing_source(ws: Path) -> None:
    result = export_to_pdf(ws / "ghost.docx", ws)

    assert result.ok is False
    assert "不存在" in (result.error or "")


def test_export_source_outside_workspace_rejected(ws: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "evil.docx"
    source.write_bytes(b"PK")

    result = export_to_pdf(source, ws)

    assert result.ok is False
    assert result.method is None


def test_export_source_is_directory(ws: Path) -> None:
    doc_dir = ws / "folder.docx"
    doc_dir.mkdir()

    result = export_to_pdf(doc_dir, ws)

    assert result.ok is False


# ──────────────────────────────────────────────────────────────────────
# Word COM fallback (stubbed win32com)
# ──────────────────────────────────────────────────────────────────────


def test_export_via_word_com_when_soffice_missing(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    """LibreOffice absent + Windows + .docx → Word COM, SaveAs2(FileFormat=17)."""
    source = _make_source(ws)
    recorder: Dict[str, Any] = {}
    _install_win32com_stub(monkeypatch, recorder)
    monkeypatch.setattr(sys, "platform", "win32")
    _patch_soffice(monkeypatch, None)

    result = export_to_pdf(source, ws)

    assert result.ok is True
    assert result.method == "word_com"

    expected_pdf = source.with_suffix(".pdf").resolve()
    assert result.output_path == str(expected_pdf)
    assert Path(result.output_path).read_bytes().startswith(b"%PDF")

    assert recorder["prog_id"] == "Word.Application"
    opened_name, opened_kwargs = recorder["opened"]
    assert Path(opened_name) == source.resolve()
    assert opened_kwargs.get("ReadOnly") is True

    file_name, file_format = recorder["saveas2"]
    assert Path(file_name) == expected_pdf
    assert file_format == 17  # wdFormatPDF

    # finally-block hygiene: document closed, Word quit.
    assert recorder.get("quit") is True
    assert recorder.get("closed", {}).get("SaveChanges") is False


def test_export_word_com_skipped_when_pywin32_missing(
    monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    """win32com unimportable → graceful ok=False (never raises)."""
    source = _make_source(ws)
    monkeypatch.setattr(sys, "platform", "win32")
    _patch_soffice(monkeypatch, None)
    monkeypatch.setitem(sys.modules, "win32com", None)
    monkeypatch.setitem(sys.modules, "win32com.client", None)

    result = export_to_pdf(source, ws)

    assert result.ok is False
    assert result.method is None
    assert "Word COM" in (result.error or "")


def test_export_word_com_not_used_for_xlsx(monkeypatch: pytest.MonkeyPatch, ws: Path) -> None:
    """Word COM opens Word docs only — .xlsx must not reach DispatchEx."""
    source = _make_source(ws, name="book.xlsx")
    recorder: Dict[str, Any] = {}
    _install_win32com_stub(monkeypatch, recorder)
    monkeypatch.setattr(sys, "platform", "win32")
    _patch_soffice(monkeypatch, None)

    result = export_to_pdf(source, ws)

    assert result.ok is False
    assert result.method is None
    assert "prog_id" not in recorder  # COM never attempted
    assert ".docx" in (result.error or "")


def test_export_word_com_skipped_on_non_windows(monkeypatch: pytest.MonkeyPatch, ws: Path) -> None:
    source = _make_source(ws)
    recorder: Dict[str, Any] = {}
    _install_win32com_stub(monkeypatch, recorder)
    monkeypatch.setattr(sys, "platform", "linux")
    _patch_soffice(monkeypatch, None)

    result = export_to_pdf(source, ws)

    assert result.ok is False
    assert "prog_id" not in recorder  # COM never attempted on non-Windows


# ──────────────────────────────────────────────────────────────────────
# Guard rails: bad timeout, never-raise contract, model defaults
# ──────────────────────────────────────────────────────────────────────


def test_export_rejects_nonpositive_timeout(ws: Path) -> None:
    source = _make_source(ws)

    result = export_to_pdf(source, ws, timeout_seconds=0)

    assert result.ok is False
    assert "timeout_seconds" in (result.error or "")


def test_export_never_raises_on_crash(monkeypatch: pytest.MonkeyPatch, ws: Path) -> None:
    """Even a crashed converter pipeline returns a failure result."""

    def boom() -> str:
        raise RuntimeError("locator exploded")

    monkeypatch.setattr(export_pdf, "_locate_soffice", boom)

    result = export_to_pdf(_make_source(ws), ws)

    assert result.ok is False
    assert result.error is not None


def test_export_pdf_result_defaults() -> None:
    result = ExportPdfResult(ok=False, error="x")

    assert result.method is None
    assert result.output_path is None


def test_export_pdf_result_rejects_unknown_method() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ExportPdfResult(ok=True, method="ghostscript")  # type: ignore[arg-type]
