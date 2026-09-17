"""Excel 公式缓存刷新（office-p2c）—— soffice 重算回写。

背景：openpyxl 保存不写公式缓存值（edit.py 已文档化），read_xlsx 只能
提示"公式计算值需在 Excel 中打开后生效"。本模块用 soffice headless 把
受管 .xlsx **原地重算**（--convert-to xlsx 产物自带缓存值），刷新后
data_only 读取直接可得计算值，预览/摘要不再带提示行。

安全与事务：
- 源文件必须在 workspace 围栏内（复用 pdf/data 的路径校验模式）；
- 重算前把当前字节写入 ``<managed_dir>/.snapshots/<ms>-<filename>``
  （与 storage.snapshot_pre_edit 同布局，可从历史版本面板恢复）；
- soffice 缺失/超时/失败 → ``ok=False``，**绝不抛异常**，绝不破坏原文件；
- 产物经 ``<stem>.xlsx`` 同名覆盖落盘（soffice 输出到临时目录再搬回）；
- Python 3.8 兼容，win7 cherry-pick 友好。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .export_pdf import _EXPORT_LOCK, _locate_soffice
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = ["ExcelRecalcRequest", "ExcelRecalcResult", "refresh_formula_cache"]

#: soffice 重算墙钟上限
_RECALC_TIMEOUT_SECONDS = 120

#: 快照目录名（与 storage.SNAPSHOT_* 布局一致）
_SNAPSHOT_DIRNAME = ".snapshots"


class ExcelRecalcRequest(BaseModel):
    """POST /office/excel/recalc 请求体。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class ExcelRecalcResult(BaseModel):
    """重算结果。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    error: Optional[str] = None


def refresh_formula_cache(request: ExcelRecalcRequest) -> ExcelRecalcResult:
    """对受管 .xlsx 执行 soffice 重算，回写公式缓存值。"""
    try:
        return _recalc_inner(request)
    except Exception as exc:  # noqa: BLE001 — 契约：绝不向路由层抛异常
        logger.exception("excel recalc crashed unexpectedly")
        return ExcelRecalcResult(
            ok=False,
            error=f"公式重算失败：内部错误（{type(exc).__name__}，详见日志）",
        )


def _recalc_inner(request: ExcelRecalcRequest) -> ExcelRecalcResult:  # noqa: PLR0911 — 失败如约的逐条早退
    workspace = validate_workspace(Path(request.workspace_path))
    source = resolve_within(workspace, Path(request.file_path))

    if source.suffix.lower() != ".xlsx":
        return ExcelRecalcResult(ok=False, error="仅支持 .xlsx 文件重算")
    if not source.is_file():
        return ExcelRecalcResult(ok=False, error="源路径不是常规文件")

    soffice_path = _locate_soffice()
    if soffice_path is None:
        return ExcelRecalcResult(
            ok=False,
            error="公式重算需要本机安装 LibreOffice（或 MS Excel 打开后保存一次）",
        )

    # 重算前快照（与 snapshot_pre_edit 同布局；best-effort，失败不阻断）
    try:
        snap_dir = source.parent / _SNAPSHOT_DIRNAME
        snap_dir.mkdir(exist_ok=True)
        snap = snap_dir / f"{int(time.time() * 1000)}-{source.name}"
        shutil.copy2(str(source), str(snap))
    except OSError:
        logger.warning("excel recalc: pre-recalc snapshot failed (ignored)", exc_info=True)

    out_dir = source.parent
    converted = out_dir / source.name  # soffice 输出 <stem>.xlsx —— 与源同名
    with tempfile.TemporaryDirectory(prefix="sage-xlsx-recalc-") as tmp:
        with _EXPORT_LOCK:
            cmd = [
                soffice_path,
                "--headless",
                "--norestore",
                "--convert-to",
                "xlsx",
                "--outdir",
                tmp,
                str(source),
            ]
            logger.info("Excel formula recalc: %s", cmd)
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    check=False,
                    timeout=_RECALC_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                return ExcelRecalcResult(
                    ok=False,
                    error=f"公式重算超时（上限 {_RECALC_TIMEOUT_SECONDS}s），进程已终止",
                )
            except OSError as exc:
                return ExcelRecalcResult(ok=False, error=f"无法启动 LibreOffice: {exc}")
        produced = Path(tmp) / source.name
        if proc.returncode != 0 or not produced.is_file():
            stderr_tail = (proc.stderr or b"")[-300:].decode("utf-8", "replace").strip()
            logger.warning(
                "Excel recalc failed (exit %s): %s", proc.returncode, stderr_tail
            )
            return ExcelRecalcResult(
                ok=False,
                error=f"公式重算失败（exit code {proc.returncode}）：{stderr_tail or '无错误输出'}",
            )
        # 原子替换：临时产物 → 受管文件（Windows Defender 锁重试）
        last_exc: Optional[Exception] = None
        for delay in (0.0, 0.1, 0.25, 0.5, 1.0):
            if delay:
                time.sleep(delay)
            try:
                produced.replace(converted)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
    return ExcelRecalcResult(ok=True)


