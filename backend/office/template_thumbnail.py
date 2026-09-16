"""Round C P5: 模板首页缩略图（P1 PDF 管线复用 + PyMuPDF 光栅化）。

管线：模板源文件（builtin 缓存 docx 或 workspace ``office/templates/``）
→ 复制进 ``office/.template-thumbs/.tmp-<key>/``（export_to_pdf 要求
source 在 workspace 内）→ :func:`export_pdf.export_to_pdf` → PyMuPDF
光栅化首页为 PNG → data URL + 磁盘缓存 ``<key>.png``。

缓存 key：builtin = sha256(template_id|size)（builtin docx 为确定性
生成，id+尺寸足够）；workspace = sha256(filename|mtime_ns|size)（文件
一变自动失效）。上限 ``_CACHE_MAX_FILES`` 按 mtime 逐出，与
pdf_preview 同策略。

失败契约：**永不 raise** —— soffice / PyMuPDF 缺失、转换超时、模板不
存在一律折叠为 ok=False（前端静默降级为无缩略图，不打扰用户）。

Python 3.8-compatible syntax，可回流 release/win7（PyMuPDF 在
requirements-bundled/py38 通道均有；缺失时 import 失败折叠为 ok=False）。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .export_pdf import export_to_pdf
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = ["TemplateThumbnailResult", "render_template_thumbnail", "THUMB_CACHE_DIRNAME"]

#: workspace 下的缩略图缓存目录。
THUMB_CACHE_DIRNAME = "office/.template-thumbs"
#: 缓存上限（张）——超出按 mtime 逐出最旧。
_CACHE_MAX_FILES = 40
#: 光栅化目标宽度（px）——列表卡片用，不追求印刷精度。
_THUMB_WIDTH = 360


class TemplateThumbnailResult(BaseModel):
    """POST /office/templates/thumbnail 的响应。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data_url: Optional[str] = Field(default=None, description="data:image/png;base64,…")
    cached: bool = Field(default=False, description="True=直接命中磁盘缓存")
    error: Optional[str] = Field(default=None)


def render_template_thumbnail(
    source: Path, workspace: Path, *, cache_key: str
) -> TemplateThumbnailResult:
    """模板源文件 → 首页 PNG 缩略图 data URL（磁盘缓存优先）。

    ``cache_key`` 由路由层按 builtin/workspace 规则算好传入（本函数只
    追加内容 size 混入，避免 key 碰撞时错图）。永不 raise。
    """
    try:
        return _render_inner(Path(source), Path(workspace), cache_key)
    except Exception as exc:  # noqa: BLE001 — 契约：绝不向路由层抛异常
        logger.exception("render_template_thumbnail crashed unexpectedly")
        return TemplateThumbnailResult(
            ok=False, error=f"缩略图生成失败：内部错误（{type(exc).__name__}，详见日志）"
        )


def _render_inner(source: Path, workspace: Path, cache_key: str) -> TemplateThumbnailResult:
    workspace = validate_workspace(workspace)
    if not source.is_file():
        return TemplateThumbnailResult(ok=False, error=f"模板文件不存在: {source.name}")

    stat = source.stat()
    key = hashlib.sha256(
        f"{cache_key}|{stat.st_size}".encode()
    ).hexdigest()[:24]
    cache_dir = workspace / THUMB_CACHE_DIRNAME
    cached_png = cache_dir / (key + ".png")
    if cached_png.is_file():
        data = cached_png.read_bytes()
        return TemplateThumbnailResult(
            ok=True,
            data_url="data:image/png;base64," + base64.b64encode(data).decode("ascii"),
            cached=True,
        )

    # PyMuPDF 在主/bundled/py38 通道都应存在；缺失时静默降级。
    try:
        import fitz  # noqa: PLC0415 — heavy import, call-time only
    except ImportError:
        return TemplateThumbnailResult(ok=False, error="PyMuPDF 不可用，无法光栅化缩略图")

    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = cache_dir / (".tmp-" + key)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        # 复制进 workspace（export_to_pdf 的围栏要求）后走 P1 转换管线
        tmp_source = tmp_dir / source.name
        shutil.copyfile(source, tmp_source)
        export = export_to_pdf(tmp_source, workspace)
        if not export.ok or not export.output_path:
            return TemplateThumbnailResult(
                ok=False, error=export.error or "PDF 转换失败"
            )
        pdf_path = Path(export.output_path)
        with fitz.open(str(pdf_path)) as doc:
            if doc.page_count == 0:
                return TemplateThumbnailResult(ok=False, error="转换产物为空 PDF")
            page = doc.load_page(0)
            zoom = _THUMB_WIDTH / max(page.rect.width, 1.0)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            png_bytes = pix.tobytes("png")
        # 原子落缓存（同名 .part → replace）
        part = cache_dir / (key + ".png.part")
        part.write_bytes(png_bytes)
        part.replace(cached_png)
        _evict_old(cache_dir)
        return TemplateThumbnailResult(
            ok=True,
            data_url="data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"),
            cached=False,
        )
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def _evict_old(cache_dir: Path) -> None:
    """按 mtime 逐出最旧，控制缓存目录规模。失败不致命。"""
    try:
        entries = sorted(
            (p for p in cache_dir.glob("*.png") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        while len(entries) > _CACHE_MAX_FILES:
            victim = entries.pop(0)
            victim.unlink()
    except OSError as exc:
        logger.warning("template thumbnail eviction failed (non-fatal): %s", exc)
