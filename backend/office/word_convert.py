"""Word 二进制格式转换（P0）：.doc ↔ .docx。

复用 ``export_pdf`` 的 soffice 定位逻辑；转换器按 LibreOffice headless →
MS Word COM（Windows）顺序尝试。契约与 PDF 导出一致：

- :func:`convert_word` 永不抛异常，失败返回 ``WordConvertResult(ok=False, error=...)``；
- 源文件与输出均限制在 workspace 内；
- 默认输出 ``<stem>.<目标格式>`` 于源文件同目录；已存在时需显式 ``overwrite=True``；
- LibreOffice 在临时子目录中转换后再原子移动到目标，避免残留半成品。
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict

from .errors import OfficeError, OfficePathError
from .export_pdf import _EXPORT_LOCK, _locate_soffice
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = ["WordConvertResult", "convert_word"]

#: 转换超时上限（秒）——防止调用方传入超大值让 soffice 长时间挂起。
_MAX_TIMEOUT_SECONDS = 1800

_SOURCE_EXTENSIONS = (".doc", ".docx")
_TARGET_FORMATS = ("docx", "doc")

#: Word COM SaveAs2 FileFormat（wdFormatDocument=0 / wdFormatXMLDocument=12）
_WD_FORMATS = {"doc": 0, "docx": 12}


class WordConvertResult(BaseModel):
    """转换结果（ok=False 时 error 为可展示失败原因）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    target_format: str
    method: Optional[str] = None
    output_path: Optional[str] = None
    error: Optional[str] = None


def convert_word(
    source: Path,
    workspace: Path,
    *,
    target_format: str = "docx",
    output_filename: Optional[str] = None,
    overwrite: bool = False,
    timeout_seconds: int = 120,
) -> WordConvertResult:
    """把 .doc/.docx 转换为目标格式（docx/doc）。

    Never raises: every failure path returns ``ok=False`` + ``error``.
    """
    with _EXPORT_LOCK:
        try:
            return _convert_inner(
                source,
                workspace,
                target_format=target_format,
                output_filename=output_filename,
                overwrite=overwrite,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 — 契约：绝不向路由层抛异常
            logger.exception("convert_word crashed unexpectedly")
            return WordConvertResult(
                ok=False,
                target_format=target_format,
                error=f"转换失败：内部错误（{type(exc).__name__}，详见日志）",
            )


def _convert_inner(  # noqa: PLR0911 — 逐条早退是失败契约的可读形式
    source: Path,
    workspace: Path,
    *,
    target_format: str,
    output_filename: Optional[str],
    overwrite: bool,
    timeout_seconds: int,
) -> WordConvertResult:
    if target_format not in _TARGET_FORMATS:
        return WordConvertResult(
            ok=False,
            target_format=target_format,
            error=f"target_format 仅支持 {_TARGET_FORMATS}，收到 {target_format!r}",
        )
    if timeout_seconds <= 0:
        return WordConvertResult(
            ok=False,
            target_format=target_format,
            error=f"timeout_seconds 必须为正整数，收到 {timeout_seconds}",
        )
    if timeout_seconds > _MAX_TIMEOUT_SECONDS:
        return WordConvertResult(
            ok=False,
            target_format=target_format,
            error=(
                f"timeout_seconds 超过上限（{_MAX_TIMEOUT_SECONDS}s），"
                f"收到 {timeout_seconds}"
            ),
        )
    try:
        workspace_path = validate_workspace(Path(workspace))
    except OfficeError as exc:
        return WordConvertResult(
            ok=False, target_format=target_format, error=f"workspace 无效: {exc}"
        )

    source_path = Path(source)
    if not source_path.exists():
        return WordConvertResult(
            ok=False, target_format=target_format, error=f"源文件不存在: {source_path}"
        )
    if source_path.suffix.lower() not in _SOURCE_EXTENSIONS:
        return WordConvertResult(
            ok=False,
            target_format=target_format,
            error="仅支持 .doc / .docx 源文件",
        )
    if source_path.suffix.lower().lstrip(".") == target_format:
        return WordConvertResult(
            ok=False, target_format=target_format, error="源格式与目标格式相同，无需转换"
        )
    try:
        resolved_source = resolve_within(workspace_path, source_path)
    except OfficePathError as exc:
        return WordConvertResult(
            ok=False,
            target_format=target_format,
            error=f"源文件不在工作区内: {exc}",
        )

    name = output_filename or resolved_source.with_suffix("." + target_format).name
    if "/" in name or "\\" in name or Path(name).is_absolute():
        return WordConvertResult(
            ok=False,
            target_format=target_format,
            error="output_filename 不能包含路径分隔符",
        )
    if Path(name).suffix.lower() != "." + target_format:
        return WordConvertResult(
            ok=False,
            target_format=target_format,
            error=f"output_filename 扩展名必须是 .{target_format}",
        )
    try:
        target = resolve_within(workspace_path, resolved_source.parent / name)
    except OfficePathError as exc:
        return WordConvertResult(
            ok=False, target_format=target_format, error=f"输出路径不在工作区内: {exc}"
        )
    if target.exists() and not overwrite:
        return WordConvertResult(
            ok=False,
            target_format=target_format,
            error=f"输出文件已存在: {target.name}（可传 overwrite=true 覆盖）",
        )

    errors = []
    soffice = _locate_soffice()
    if soffice:
        ok, detail = _convert_with_libreoffice(
            soffice,
            resolved_source,
            target,
            target_format=target_format,
            timeout_seconds=timeout_seconds,
        )
        if ok:
            return WordConvertResult(
                ok=True,
                target_format=target_format,
                method="libreoffice",
                output_path=str(target),
            )
        errors.append(detail)
    else:
        errors.append("未找到 LibreOffice（soffice）")

    if sys.platform == "win32":
        ok, detail = _convert_with_word_com(resolved_source, target, target_format)
        if ok:
            return WordConvertResult(
                ok=True,
                target_format=target_format,
                method="word_com",
                output_path=str(target),
            )
        errors.append(detail)

    return WordConvertResult(
        ok=False,
        target_format=target_format,
        error=(
            "未找到可用的转换器（LibreOffice/Word COM），无法转换。"
            + ("详情：" + "；".join(errors) if errors else "")
        ),
    )


def _convert_with_libreoffice(
    soffice_path: str,
    source: Path,
    target: Path,
    *,
    target_format: str,
    timeout_seconds: int,
) -> Tuple[bool, str]:
    """在临时子目录转换后原子移动到目标；返回 (ok, detail)。"""
    temp_dir = target.parent / f".convert-{uuid.uuid4().hex}"
    try:
        temp_dir.mkdir()
        cmd = [
            soffice_path,
            "--headless",
            "--norestore",
            "--convert-to",
            target_format,
            "--outdir",
            str(temp_dir),
            str(source),
        ]
        logger.info("Converting Word format via LibreOffice: %s", cmd)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, f"LibreOffice 转换超时（上限 {timeout_seconds}s），进程已终止"
        except OSError as exc:
            return False, f"无法启动 LibreOffice: {exc}"
        if proc.returncode != 0:
            return False, (
                f"LibreOffice 转换失败（exit code {proc.returncode}）："
                f"{_tail(proc.stderr) or '无错误输出'}"
            )
        produced = temp_dir / f"{source.stem}.{target_format}"
        if not produced.exists():
            candidates = list(temp_dir.glob(f"*.{target_format}"))
            if not candidates:
                return False, "LibreOffice 报告成功，但未找到输出文件"
            produced = candidates[0]
        os.replace(produced, target)  # noqa: PTH105 — Path.replace 在 Windows 上跨盘时不可靠
        return True, ""
    except OSError as exc:
        return False, f"写入输出文件失败: {exc}"
    finally:
        with contextlib.suppress(OSError):
            for leftover in temp_dir.iterdir():
                leftover.unlink()
            temp_dir.rmdir()


def _convert_with_word_com(
    source: Path, target: Path, target_format: str
) -> Tuple[bool, str]:
    """Windows 回退：Word COM ``SaveAs2``（FileFormat 0=doc / 12=docx）。

    Office 2007（Win7 LTS 常见）没有 ``SaveAs2``，回退到 ``SaveAs``。
    """
    try:
        import win32com.client  # lazy: pywin32, Windows only
    except ImportError:
        return False, "Word COM 不可用（未安装 pywin32）"

    word = None
    document = None
    temp_target = target.with_name(
        f".{target.stem}.{uuid.uuid4().hex}.com{target.suffix}"
    )
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(str(source), ReadOnly=True)
        _word_save_as(document, temp_target, target_format)
        # 必须先关闭文档并退出 Word —— Word 持有输出文件的句柄，
        # 未释放时 os.replace 在 Windows 上会 PermissionError（拒绝访问）。
        document.Close(SaveChanges=False)
        document = None
        word.Quit()
        word = None
        os.replace(temp_target, target)  # noqa: PTH105 — 与 LibreOffice 路径一致的原子替换
        logger.info("Word COM conversion succeeded: %s", target)
        return True, ""
    except Exception as exc:  # noqa: BLE001 — COM 失败统一折叠
        logger.warning("Word COM conversion failed: %s", exc)
        return False, f"Word COM 转换失败: {exc}"
    finally:
        if document is not None:
            with contextlib.suppress(Exception):
                document.Close(SaveChanges=False)
        if word is not None:
            with contextlib.suppress(Exception):
                word.Quit()
        with contextlib.suppress(OSError):
            if temp_target.exists():
                temp_target.unlink()


def _word_save_as(document, target: Path, target_format: str) -> None:
    """用 Word COM 保存为目标格式；Office 2007 无 ``SaveAs2`` 时回退 ``SaveAs``。"""
    file_format = _WD_FORMATS[target_format]
    save_as2 = getattr(document, "SaveAs2", None)
    if save_as2 is not None:
        save_as2(str(target), FileFormat=file_format)
        return
    document.SaveAs(str(target), FileFormat=file_format)


def _tail(stream: Optional[bytes], limit: int = 400) -> str:
    if not stream:
        return ""
    return stream[-limit:].decode("utf-8", "replace").strip()
