# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Word 目录真页码：Word COM 刷新域可选通道（Round 39）。

R29 的 TOC 是 fldChar 复杂域 + 静态缓存行（72-word-toc-static-cache.md）：
文档打开即有目录骨架，页码是生成期占位缓存。本模块提供"刷新域"通道——
本机装有 Word + pywin32 时，用 Word COM 把 ``TablesOfContents`` 逐个
``Update()``（重分页并重算页码与条目）后落盘；否则返回可读降级理由，
绝不向调用层抛异常（契约与 ``export_pdf.export_to_pdf`` 一致）。

安全姿态（对齐 ``export_pdf._convert_with_word_com``，并因"可写打开"
加一层防线）：

- pywin32 懒加载——未安装时优雅降级，不影响默认依赖面；
- ``DispatchEx`` 独立实例 + ``Visible=False`` + ``DisplayAlerts=0``；
- ``AutomationSecurity=3``（msoAutomationSecurityForceDisable）：强制
  禁用宏，打开不可信 docx 时不执行任何活动内容；
- ``finally`` 兜底 ``Close(SaveChanges=False)`` + ``Quit()``，转换崩溃
  也不泄漏隐藏的 WINWORD.EXE 进程；
- 源路径经 ``validate_workspace`` + ``resolve_within`` 工作区围栏把守，
  越界直接拒绝。

Python 3.8-compatible syntax (typing.* generics, no PEP 604)，与
``backend/office`` 其余模块同口径；**新功能不回流 release/win7**
（31-win7-lts.md §2）。
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
from pathlib import Path
from typing import Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .errors import OfficeError
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = ["TocRefreshResult", "refresh_toc_page_numbers", "word_com_applicable"]

#: Word COM 是进程内单实例资源，与 export_pdf 同款串行锁，免去并发心智负担。
_TOC_REFRESH_LOCK = threading.Lock()


class TocRefreshResult(BaseModel):
    """TOC 域刷新结果。``ok=False`` 时 ``error`` 带中文可展示原因。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="刷新是否成功（含文档无目录的 no-op 成功）")
    toc_count: int = Field(
        default=0,
        description="成功更新的目录（TablesOfContents）个数；失败/未执行为 0",
    )
    method: Literal["word_com"] = Field(
        default="word_com",
        description="刷新通道；当前唯一实现为 Word COM（Windows + pywin32）",
    )
    error: Optional[str] = Field(
        default=None,
        description="失败原因（中文，可直接展示给用户）；成功为 None",
    )


def word_com_applicable() -> Tuple[bool, str]:
    """Word COM 通道是否可能可用；不可用时给出原因。"""
    if sys.platform != "win32":
        return False, "仅 Windows 可用（需本机安装 Microsoft Word）"
    return True, ""


def refresh_toc_page_numbers(source: Path, workspace: Path) -> TocRefreshResult:
    """刷新托管 docx 内全部 TOC 域为真页码并落盘。

    Never raises：所有失败路径返回 ``TocRefreshResult(ok=False, error=...)``
    并记日志。文档没有目录时同样成功（``toc_count=0`` 的 no-op），便于
    LLM 生成后无条件调用。

    Args:
        source: 待刷新 .docx 路径（必须存在且位于 ``workspace`` 内）。
        workspace: 托管工作区根目录，用于路径围栏校验。
    """
    with _TOC_REFRESH_LOCK:
        return _refresh_toc_inner(source, workspace)


def _refresh_toc_inner(  # noqa: PLR0911 — 逐条早退是这套失败契约的可读形式
    source: Path, workspace: Path
) -> TocRefreshResult:
    # ── 路径围栏（镜像 export_pdf._export_to_pdf_inner）──────────────
    try:
        resolved_workspace = validate_workspace(Path(workspace))
    except OfficeError as exc:
        logger.warning("Invalid workspace for TOC refresh: %s", exc)
        return TocRefreshResult(ok=False, error=f"workspace 无效: {exc}")

    source_path = Path(source)
    if not source_path.exists():
        logger.warning("TOC refresh source does not exist: %s", source_path)
        return TocRefreshResult(ok=False, error=f"源文件不存在: {source_path}")

    if source_path.suffix.lower() != ".docx":
        return TocRefreshResult(
            ok=False,
            error=f"不支持的源文件类型 '{source_path.suffix or '无扩展名'}'（仅支持 .docx）",
        )

    try:
        resolved_source = resolve_within(resolved_workspace, source_path)
    except OfficeError:
        logger.warning("TOC refresh source escapes workspace: %s", source_path)
        return TocRefreshResult(ok=False, error="源文件不在 workspace 内，已拒绝刷新")

    if not resolved_source.is_file():
        return TocRefreshResult(ok=False, error=f"源路径不是常规文件: {resolved_source.name}")

    applicable, reason = word_com_applicable()
    if not applicable:
        return TocRefreshResult(ok=False, error=f"Word COM 不可用：{reason}")

    return _refresh_with_word_com(resolved_source)


def _refresh_with_word_com(docx_path: Path) -> TocRefreshResult:
    """经 Word COM 打开文档、逐个 Update TOC 后保存。

    pywin32 懒加载——缺失时降级为带安装引导的失败而非硬错误。
    """
    try:
        import pythoncom  # lazy: pywin32, Windows only
        import win32com.client  # noqa: F401 — 确认可导入后才启动 COM
    except ImportError:
        logger.info("pywin32 not available — TOC refresh skipped")
        return TocRefreshResult(
            ok=False,
            error=(
                "Word COM 不可用（未安装 pywin32）。可执行 "
                "pip install pywin32 启用；或在 Word 中打开文档后 "
                "Ctrl+A → F9 手动更新目录域"
            ),
        )

    word = None
    doc = None
    co_initialized = False
    try:
        # 工具执行可能落在子进程/线程池线程：逐线程初始化 COM。
        with contextlib.suppress(Exception):
            pythoncom.CoInitialize()
            co_initialized = True

        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        # msoAutomationSecurityForceDisable：打开期间强制禁宏。
        word.AutomationSecurity = 3
        doc = word.Documents.Open(str(docx_path), ReadOnly=False, AddToRecentFiles=False)

        tocs = doc.TablesOfContents
        toc_count = int(tocs.Count)
        for i in range(1, toc_count + 1):
            tocs.Item(i).Update()
        if toc_count > 0:
            doc.Save()
        else:
            logger.info("TOC refresh no-op (no TablesOfContents): %s", docx_path)
        logger.info("Word COM TOC refresh succeeded: %s (%d TOC)", docx_path, toc_count)
        return TocRefreshResult(ok=True, toc_count=toc_count)
    except Exception as exc:
        logger.warning("Word COM TOC refresh failed: %s", exc)
        return TocRefreshResult(ok=False, error=f"Word COM 目录刷新失败: {exc}")
    finally:
        if doc is not None:
            with contextlib.suppress(Exception):
                doc.Close(SaveChanges=False)
        if word is not None:
            with contextlib.suppress(Exception):
                word.Quit()
        if co_initialized:
            with contextlib.suppress(Exception):
                pythoncom.CoUninitialize()
