"""Round A P1: PDF 中转高保真预览（docx/xlsx/pptx → 缓存 PDF → data URL）。

复用 :mod:`backend.office.export_pdf` 的本机转换器（LibreOffice /
Word COM），把托管文档转成 PDF 后以 ``data:application/pdf;base64,``
返回，前端用 Chromium 内置 viewer 内嵌渲染 —— 字体/边距/分页/页眉页脚/
多级编号在应用内即可见，FormatSpec 效果不再必须打开本机 Office 验证。

与「导出 PDF」（export-pdf 端点，产物落在源文件旁）不同，预览产物写进
工作区 ``office/.preview-cache/`` 缓存目录：

- 缓存 key = 源文件相对路径 + mtime_ns + size 的 sha256 前 24 位 →
  ``<key>.pdf``。源文件一变（编辑/快照回滚）key 即失效，无需显式失效
  逻辑；
- 命中直接读缓存，跳过转换子进程（LibreOffice 单次转换秒级，命中后预
  览毫秒级返回）；
- 目录内最多保留 :data:`_CACHE_MAX_FILES` 份，超限按 mtime 逐出最旧
  （单工作区预览缓存有限、可随时重建，不值得上 LRU 数据库）。

失败契约与 export_to_pdf 相同：**永不 raise**，一切失败都折叠为
``PdfPreviewResult(ok=False, error=…)``。

Python 3.8-compatible syntax，可回流 release/win7。
"""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .errors import OfficeError
from .export_pdf import export_to_pdf
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = ["PdfPreviewResult", "render_pdf_preview", "PREVIEW_CACHE_DIRNAME"]

#: 预览缓存目录（工作区相对）。`.` 前缀让目录扫描类功能默认忽略它。
PREVIEW_CACHE_DIRNAME = "office/.preview-cache"

#: 单工作区缓存上限（份）。超限按 mtime 逐出最旧。
_CACHE_MAX_FILES = 20

#: 返回 data URL 的 PDF 大小上限 —— 与 artifact_reader.MAX_PDF_BYTES
#: 同口径（20MB）：更大的 base64 响应会拖垮 renderer。
_MAX_PREVIEW_PDF_BYTES = 20_000_000

#: 支持的源扩展名（与 export_pdf._SUPPORTED_EXTENSIONS 一致）。
_SUPPORTED_EXTENSIONS = (".docx", ".xlsx", ".pptx")


class PdfPreviewResult(BaseModel):
    """POST /office/pdf-preview 响应。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="预览生成是否成功")
    data_url: Optional[str] = Field(
        default=None, description="data:application/pdf;base64,… 内嵌预览地址"
    )
    cached: bool = Field(default=False, description="是否命中缓存（未启动转换器）")
    error: Optional[str] = Field(default=None, description="失败原因；成功时为 None")


def _cache_key(source: Path, workspace: Path) -> str:
    """源文件身份指纹：相对路径 + mtime_ns + size。"""
    stat = source.stat()
    try:
        rel = str(source.relative_to(workspace))
    except ValueError:  # resolve_within 已保证在内，防御性兜底
        rel = str(source)
    raw = f"{rel}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _evict_old_entries(cache_dir: Path) -> None:
    """超限时按 mtime 逐出最旧缓存；任何失败只记日志不阻断预览。"""
    try:
        entries = sorted(
            cache_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for stale in entries[_CACHE_MAX_FILES:]:
            stale.unlink(missing_ok=True)
    except OSError:
        logger.debug("pdf_preview: 缓存逐出失败（忽略）", exc_info=True)


def _to_data_url(pdf_path: Path) -> Optional[str]:
    size = pdf_path.stat().st_size
    if size > _MAX_PREVIEW_PDF_BYTES:
        return None
    data = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
    return f"data:application/pdf;base64,{data}"


def render_pdf_preview(source: Path, workspace: Path) -> PdfPreviewResult:
    """把工作区内的 docx/xlsx/pptx 渲染为高保真 PDF 预览。

    永不 raise —— 所有失败折叠为 ``ok=False``。
    """
    try:
        return _render_inner(source, workspace)
    except Exception as exc:  # noqa: BLE001 — 契约：绝不向路由层抛异常
        logger.exception("render_pdf_preview crashed unexpectedly")
        return PdfPreviewResult(
            ok=False,
            error=f"高保真预览失败：内部错误（{type(exc).__name__}，详见日志）",
        )


def _render_inner(  # noqa: PLR0911 — 与 export_pdf 同口径：逐条早退是失败契约的可读形式
    source: Path, workspace: Path
) -> PdfPreviewResult:
    try:
        resolved_workspace = validate_workspace(Path(workspace))
        source_path = resolve_within(resolved_workspace, Path(source))
    except OfficeError as exc:
        return PdfPreviewResult(ok=False, error=f"路径无效: {exc}")

    if not source_path.is_file():
        return PdfPreviewResult(ok=False, error=f"源文件不存在: {source_path.name}")
    if source_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        return PdfPreviewResult(
            ok=False, error=f"不支持的文件类型: {source_path.suffix}（仅 docx/xlsx/pptx）"
        )

    cache_dir = resolved_workspace / PREVIEW_CACHE_DIRNAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_pdf = cache_dir / f"{_cache_key(source_path, resolved_workspace)}.pdf"

    if cached_pdf.is_file():
        data_url = _to_data_url(cached_pdf)
        if data_url is not None:
            return PdfPreviewResult(ok=True, data_url=data_url, cached=True)
        return PdfPreviewResult(ok=False, error="预览 PDF 超过 20MB 上限，请使用导出 PDF")

    # export_to_pdf 把产物写在源文件旁（<stem>.pdf）——预览不能覆盖用户
    # 可能已导出的同名文件，所以先转到缓存目录里的临时副本目录结构：
    # 直接把源文件转换产物 <stem>.pdf 生成后 move 进缓存。为避免与用户
    # 手动导出的 <stem>.pdf 冲突，转换在缓存目录的临时子目录中进行。
    tmp_dir = cache_dir / f".tmp-{cached_pdf.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_source = tmp_dir / source_path.name
    try:
        import shutil

        shutil.copyfile(str(source_path), str(tmp_source))
        result = export_to_pdf(tmp_source, resolved_workspace)
        if not result.ok or not result.output_path:
            return PdfPreviewResult(ok=False, error=result.error or "转换失败")
        produced = Path(result.output_path)
        if not produced.is_file():
            return PdfPreviewResult(ok=False, error="转换器报告成功但未找到输出 PDF")
        produced.replace(cached_pdf)
        _evict_old_entries(cache_dir)
        data_url = _to_data_url(cached_pdf)
        if data_url is None:
            return PdfPreviewResult(ok=False, error="预览 PDF 超过 20MB 上限，请使用导出 PDF")
        return PdfPreviewResult(ok=True, data_url=data_url, cached=False)
    finally:
        import shutil as _shutil

        _shutil.rmtree(str(tmp_dir), ignore_errors=True)
