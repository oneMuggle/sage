"""Export managed Office documents (.docx/.xlsx/.pptx) to PDF.

Item 2.7 of the Office parity plan (batch 2): convert an existing managed
document to PDF using **locally installed converters** — the app never
bundles or downloads a converter. Two backends, tried in order:

1. **LibreOffice headless** (cross-platform): ``soffice --headless
   --norestore --convert-to pdf --outdir <dir> <src>``, executed with an
   argv list (never ``shell=True``), stdout/stderr captured, wall-clock
   bounded by ``timeout_seconds`` (``subprocess.run`` kills the child on
   ``TimeoutExpired``). The executable is located via, in order:
   ``SAGE_SOFFICE_PATH`` env var → ``shutil.which("soffice")`` →
   well-known Windows/mac/Linux install paths.
2. **MS Word COM automation** (Windows only, ``.docx`` sources) via a
   lazy ``import win32com.client``: ``Documents.Open`` +
   ``SaveAs2(pdf, FileFormat=17)``. ``Quit()`` is guaranteed in a
   ``finally`` block; every COM touch is inside a try/except.

Route-layer contract (``backend/api/office_routes.py``):

- :func:`export_to_pdf` **never raises**. Every failure — missing source,
  unsupported extension, workspace escape, converter crash, timeout — is
  reported as ``ExportPdfResult(ok=False, error=...)`` and logged via the
  module logger.
- Output lands **next to the source** as ``<stem>.pdf``. An existing file
  is overwritten (export is an explicit user action).
- The source must resolve **inside** ``workspace`` (via
  :func:`backend.office.path_safety.resolve_within`); the derived output
  path is therefore inside the workspace by construction.

Python 3.8-compatible syntax (typing.* generics, no PEP 604) so the
module can be cherry-picked to ``release/win7`` like the rest of
``backend/office``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .errors import OfficeError
from .path_safety import is_within, resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = ["ExportPdfResult", "export_to_pdf"]

#: Managed document types that may be exported to PDF.
_SUPPORTED_EXTENSIONS = (".docx", ".xlsx", ".pptx")

#: Word COM can only open Word documents — never .xlsx/.pptx.
_WORD_COM_EXTENSIONS = (".docx",)

#: Well-known LibreOffice install locations, per platform. Consulted only
#: when neither ``SAGE_SOFFICE_PATH`` nor ``shutil.which`` finds soffice.
_WINDOWS_SOFFICE_CANDIDATES: Tuple[str, ...] = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
_MACOS_SOFFICE_CANDIDATES: Tuple[str, ...] = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)
_LINUX_SOFFICE_CANDIDATES: Tuple[str, ...] = (
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/opt/libreoffice/program/soffice",
)

#: wdFormatPDF — Word's SaveAs2 constant for "save as PDF".
_WD_FORMAT_PDF = 17


class ExportPdfResult(BaseModel):
    """Result of an explicit PDF export (item 2.7).

    ``method`` is ``None`` whenever ``ok`` is ``False`` (no converter ran
    to completion). ``output_path`` is populated only on success.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="导出是否成功")
    method: Optional[Literal["libreoffice", "word_com"]] = Field(
        default=None,
        description="实际使用的转换器；失败时为 None",
    )
    output_path: Optional[str] = Field(
        default=None,
        description="生成的 PDF 绝对路径（位于源文件旁，<stem>.pdf）",
    )
    error: Optional[str] = Field(
        default=None,
        description="失败原因；成功时为 None",
    )


# ──────────────────────────────────────────────────────────────────────
# LibreOffice backend — locate the executable, then run the conversion
# ──────────────────────────────────────────────────────────────────────


def _candidate_soffice_paths() -> List[str]:
    """Platform-specific well-known soffice install paths."""
    if sys.platform == "win32":
        return list(_WINDOWS_SOFFICE_CANDIDATES)
    if sys.platform == "darwin":
        return list(_MACOS_SOFFICE_CANDIDATES)
    return list(_LINUX_SOFFICE_CANDIDATES)


def _locate_soffice() -> Optional[str]:
    """Locate the LibreOffice executable, or ``None`` if not installed.

    Detection order: ``SAGE_SOFFICE_PATH`` env var (must exist on disk;
    a stale value is logged and skipped) → ``shutil.which("soffice")``
    (respects ``PATH``) → well-known per-platform install paths.
    """
    env_path = os.environ.get("SAGE_SOFFICE_PATH")
    if env_path:
        if Path(env_path).exists():
            logger.debug("SAGE_SOFFICE_PATH overrides soffice location: %s", env_path)
            return env_path
        logger.warning(
            "SAGE_SOFFICE_PATH is set but the path does not exist: %s — "
            "falling back to PATH/well-known locations",
            env_path,
        )

    which_hit = shutil.which("soffice")
    if which_hit:
        logger.debug("soffice found on PATH: %s", which_hit)
        return which_hit

    for candidate in _candidate_soffice_paths():
        if Path(candidate).exists():
            logger.debug("soffice found at well-known path: %s", candidate)
            return candidate
    return None


def _convert_with_libreoffice(
    soffice_path: str,
    source: Path,
    out_pdf: Path,
    *,
    timeout_seconds: int,
) -> Tuple[bool, str]:
    """Run ``soffice --headless --convert-to pdf``; return (ok, detail).

    argv-list subprocess (no shell), captured stdout/stderr, bounded by
    ``timeout_seconds`` — ``subprocess.run`` already kills the child when
    ``TimeoutExpired`` fires. ``detail`` is a user-presentable failure
    string when ``ok`` is ``False`` (empty on success).
    """
    out_dir = out_pdf.parent
    cmd = [
        soffice_path,
        "--headless",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(source),
    ]
    logger.info("Exporting to PDF via LibreOffice: %s", cmd)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "LibreOffice conversion exceeded %ss — child process killed",
            timeout_seconds,
        )
        return False, f"LibreOffice 转换超时（timeout，上限 {timeout_seconds}s），进程已终止"
    except OSError as exc:
        logger.warning("LibreOffice executable could not be launched: %s", exc)
        return False, f"无法启动 LibreOffice: {exc}"

    if proc.returncode != 0:
        stderr_tail = _tail(proc.stderr)
        logger.warning(
            "LibreOffice conversion failed (exit code %s): %s",
            proc.returncode,
            stderr_tail,
        )
        return False, (
            f"LibreOffice 转换失败（exit code {proc.returncode}）："
            f"{stderr_tail or '无错误输出'}"
        )
    if not out_pdf.exists():
        logger.warning("LibreOffice reported success but output PDF is missing: %s", out_pdf)
        return False, "LibreOffice 报告成功，但未找到输出 PDF 文件"
    return True, ""


def _tail(stream: Optional[bytes], limit: int = 400) -> str:
    """Decode the tail of captured subprocess output for error messages."""
    if not stream:
        return ""
    return stream[-limit:].decode("utf-8", "replace").strip()


# ──────────────────────────────────────────────────────────────────────
# MS Word COM fallback (Windows, .docx)
# ──────────────────────────────────────────────────────────────────────


def _word_com_applicable(ext: str) -> Tuple[bool, str]:
    """Whether the Word COM fallback may handle this source; else the reason."""
    if sys.platform != "win32":
        return False, "仅 Windows 可用"
    if ext not in _WORD_COM_EXTENSIONS:
        return False, "仅支持 .docx 源文件"
    return True, ""


def _convert_with_word_com(source: Path, out_pdf: Path) -> Tuple[bool, str]:
    """Convert ``source`` to PDF via Word COM (``SaveAs2``, wdFormatPDF).

    pywin32 is imported lazily — when missing the branch is skipped with a
    reason instead of failing hard. ``Quit()`` runs in ``finally`` so a
    crashed conversion never leaks a hidden WINWORD.EXE process.
    """
    try:
        import win32com.client  # lazy: pywin32, Windows only
    except ImportError:
        logger.info("pywin32 not available — Word COM export skipped")
        return False, "Word COM 不可用（未安装 pywin32）"

    word = None
    doc = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(source), ReadOnly=True)
        doc.SaveAs2(str(out_pdf), FileFormat=_WD_FORMAT_PDF)
        logger.info("Word COM export succeeded: %s", out_pdf)
        return True, ""
    except Exception as exc:
        logger.warning("Word COM export failed: %s", exc)
        return False, f"Word COM 导出失败: {exc}"
    finally:
        if doc is not None:
            with contextlib.suppress(Exception):
                doc.Close(SaveChanges=False)
        if word is not None:
            with contextlib.suppress(Exception):
                word.Quit()


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────


def export_to_pdf(
    source: Path,
    workspace: Path,
    *,
    timeout_seconds: int = 120,
) -> ExportPdfResult:
    """Export a managed .docx/.xlsx/.pptx to PDF next to the source.

    Tries LibreOffice headless first, then (Windows + .docx) Word COM.
    Never raises: every failure path returns
    ``ExportPdfResult(ok=False, error=...)`` and is logged.

    Args:
        source: Path to the source document (must exist and lie inside
            ``workspace`` after resolution).
        workspace: The managed workspace directory that bounds both the
            source and the derived ``<stem>.pdf`` output.
        timeout_seconds: Wall-clock limit for the LibreOffice child
            process; must be positive.

    Returns:
        ExportPdfResult with ``method``/``output_path`` set on success.
    """
    try:
        return _export_to_pdf_inner(source, workspace, timeout_seconds=timeout_seconds)
    except Exception as exc:  # noqa: BLE001 — 契约：绝不向路由层抛异常
        logger.exception("export_to_pdf crashed unexpectedly")
        return ExportPdfResult(
            ok=False,
            error=f"导出 PDF 失败：内部错误（{type(exc).__name__}，详见日志）",
        )


def _export_to_pdf_inner(  # noqa: PLR0911 — 逐条早退是这套失败契约的可读形式
    source: Path,
    workspace: Path,
    *,
    timeout_seconds: int,
) -> ExportPdfResult:
    if timeout_seconds <= 0:
        return ExportPdfResult(
            ok=False,
            error=f"timeout_seconds 必须为正整数，收到 {timeout_seconds}",
        )

    try:
        resolved_workspace = validate_workspace(Path(workspace))
    except OfficeError as exc:
        logger.warning("Invalid workspace for PDF export: %s", exc)
        return ExportPdfResult(ok=False, error=f"workspace 无效: {exc}")

    source_path = Path(source)
    if not source_path.exists():
        logger.warning("PDF export source does not exist: %s", source_path)
        return ExportPdfResult(ok=False, error=f"源文件不存在: {source_path}")

    ext = source_path.suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        return ExportPdfResult(
            ok=False,
            error=(f"不支持的源文件类型 '{ext or '无扩展名'}'" f"（仅支持 .docx/.xlsx/.pptx）"),
        )

    # Workspace boundary: collapse ``..``/symlinks and reject escapes. The
    # output path is derived from the *resolved* source parent, which keeps
    # it inside the workspace by construction.
    try:
        resolved_source = resolve_within(resolved_workspace, source_path)
    except OfficeError:
        logger.warning("PDF export source escapes workspace: %s", source_path)
        return ExportPdfResult(ok=False, error="源文件不在 workspace 内，已拒绝导出")

    if not resolved_source.is_file():
        return ExportPdfResult(ok=False, error=f"源路径不是常规文件: {source_path.name}")

    out_pdf = resolved_source.parent / (resolved_source.stem + ".pdf")
    # Defense-in-depth: re-assert the derived output stays in the workspace.
    if not is_within(resolved_workspace, out_pdf):
        return ExportPdfResult(ok=False, error="输出路径越界，已拒绝导出")

    # Backend 1: LibreOffice headless.
    soffice_path = _locate_soffice()
    if soffice_path is not None:
        converted, detail = _convert_with_libreoffice(
            soffice_path,
            resolved_source,
            out_pdf,
            timeout_seconds=timeout_seconds,
        )
        if converted:
            return ExportPdfResult(
                ok=True,
                method="libreoffice",
                output_path=str(out_pdf),
            )
        logger.info("LibreOffice export failed: %s", detail)
    else:
        detail = "未找到 LibreOffice（soffice）"

    # Backend 2: MS Word COM (Windows, .docx only).
    applicable, reason = _word_com_applicable(ext)
    if applicable:
        converted, com_detail = _convert_with_word_com(resolved_source, out_pdf)
        if converted:
            return ExportPdfResult(
                ok=True,
                method="word_com",
                output_path=str(out_pdf),
            )
        detail = f"{detail}；Word COM 回退也失败: {com_detail}"
    else:
        detail = f"{detail}；Word COM 回退不可用（{reason}）"

    logger.warning("PDF export failed for %s: %s", resolved_source.name, detail)
    return ExportPdfResult(ok=False, error=detail)
