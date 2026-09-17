"""旧格式 (.doc/.xls/.ppt) → 现代格式转换（office-p1c）。

导入时机与安全边界：
- 前端先把用户文件**原样**暂存进受管目录（既有 import 网关），然后调用
  本模块把暂存文件就地转换为现代格式 —— 因此参与转换的源文件必然已在
  workspace 路径围栏之内，不引入工作区外任意读。
- soffice 定位与进程锁复用 :mod:`.export_pdf`（单实例 profile 串行）。
- 转换产物落在源文件同目录（staging 目录），源旧格式文件删除。
- 失败契约：**永不 raise** —— soffice 缺失 / 超时 / 转换失败 / 越界都
  折算为 ``LegacyImportResult(ok=False, error=...)``，调用方引导用户
  （如"导入旧格式需要本机安装 LibreOffice"）。

Python 3.8 兼容（typing.* generics，无 PEP 604），可 cherry-pick 到
``release/win7``。
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict

from .export_pdf import _EXPORT_LOCK, _locate_soffice
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = ["LegacyImportResult", "convert_legacy_import"]

#: 旧扩展名 → soffice 目标格式
_LEGACY_TO_TARGET: Dict[str, str] = {
    ".doc": "docx",
    ".xls": "xlsx",
    ".ppt": "pptx",
}

#: 暂存源文件大小上限（与 office 读取上限同口径）
MAX_LEGACY_SOURCE_BYTES = 50 * 1024 * 1024

#: soffice 单文件转换墙钟上限
_LEGACY_TIMEOUT_SECONDS = 120


class LegacyImportRequest(BaseModel):
    """POST /office/import/convert-legacy 请求体。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class LegacyImportResult(BaseModel):
    """转换结果：``converted_path``/``converted_filename`` 仅在 ok=True 时有效。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    converted_path: Optional[str] = None
    converted_filename: Optional[str] = None
    doc_type: Optional[str] = None
    error: Optional[str] = None


def convert_legacy_import(request: LegacyImportRequest) -> LegacyImportResult:
    """把 workspace 内的旧格式暂存文件就地转换为现代格式。"""
    try:
        return _convert_inner(request)
    except Exception as exc:  # noqa: BLE001 — 契约：绝不向路由层抛异常
        logger.exception("legacy import crashed unexpectedly")
        return LegacyImportResult(
            ok=False,
            error=f"旧格式转换失败：内部错误（{type(exc).__name__}，详见日志）",
        )


def _convert_inner(request: LegacyImportRequest) -> LegacyImportResult:  # noqa: PLR0911 — 失败契约的逐条早退
    workspace = validate_workspace(Path(request.workspace_path))
    source = resolve_within(workspace, Path(request.file_path))

    ext = source.suffix.lower()
    target = _LEGACY_TO_TARGET.get(ext)
    if target is None:
        return LegacyImportResult(
            ok=False,
            error=f"不支持的旧格式扩展名 {ext!r}（仅支持 .doc/.xls/.ppt）",
        )
    if not source.is_file():
        return LegacyImportResult(ok=False, error="源路径不是常规文件")
    if source.stat().st_size > MAX_LEGACY_SOURCE_BYTES:
        return LegacyImportResult(ok=False, error="文件超过 50MB 导入上限")

    soffice_path = _locate_soffice()
    if soffice_path is None:
        return LegacyImportResult(
            ok=False,
            error="导入旧格式（.doc/.xls/.ppt）需要本机安装 LibreOffice",
        )

    out_dir = source.parent
    converted = out_dir / (source.stem + "." + target)
    with tempfile.TemporaryDirectory(prefix="sage-legacy-") as tmp:
        with _EXPORT_LOCK:
            cmd = [
                soffice_path,
                "--headless",
                "--norestore",
                "--convert-to",
                target,
                "--outdir",
                tmp,
                str(source),
            ]
            logger.info("Legacy import conversion: %s", cmd)
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, check=False, timeout=_LEGACY_TIMEOUT_SECONDS
                )
            except subprocess.TimeoutExpired:
                return LegacyImportResult(
                    ok=False,
                    error=f"旧格式转换超时（上限 {_LEGACY_TIMEOUT_SECONDS}s），进程已终止",
                )
            except OSError as exc:
                return LegacyImportResult(
                    ok=False, error=f"无法启动 LibreOffice: {exc}"
                )
        produced = Path(tmp) / (source.stem + "." + target)
        if proc.returncode != 0 or not produced.is_file():
            stderr_tail = (proc.stderr or b"")[-300:].decode("utf-8", "replace").strip()
            logger.warning(
                "Legacy conversion failed (exit %s): %s", proc.returncode, stderr_tail
            )
            return LegacyImportResult(
                ok=False,
                error=f"旧格式转换失败（exit code {proc.returncode}）：{stderr_tail or '无错误输出'}",
            )
        # 产物搬进 staging 目录（COPYFILE 语义：目标已存在则失败，防御竞态）
        shutil.copyfile(str(produced), str(converted))

    # 转换成功后删除旧格式原件（staging 目录内的临时副本，非用户原件）
    with contextlib.suppress(OSError):
        os.unlink(source)

    return LegacyImportResult(
        ok=True,
        converted_path=str(converted),
        converted_filename=converted.name,
        doc_type=target,
    )

