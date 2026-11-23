"""Extraction service (M6b): validate, select backend, normalize output."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from ..errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficeSizeLimitError,
)
from ..path_safety import resolve_within
from ..storage import validate_workspace
from .base import (
    StructuredDocument,
    extractor_available,
    get_extractor,
    list_extractors,
)
from .tables import assess_table_complexity

logger = logging.getLogger(__name__)

__all__ = ["ExtractRequest", "ExtractResult", "extract_document"]

MAX_EXTRACT_BYTES = 200 * 1024 * 1024
_SUPPORTED_SUFFIXES = (".docx", ".xlsx", ".pptx", ".pdf", ".csv", ".md", ".html", ".txt")
_AUTO_ORDER = ("docling", "markitdown", "light")
#: 复杂表格兜底时优先使用的结构化后端（能给出真正的表格网格）。
_TABLE_FALLBACK_BACKEND = "docling"


class ExtractRequest(BaseModel):
    """POST /office/extract request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    backend: Literal["auto", "light", "markitdown", "docling"] = Field(
        default="auto", description="auto 优先可选后端，缺失时回退 light"
    )
    max_chars: int = Field(default=200_000, ge=1000, le=2_000_000)
    table_fallback: Literal["auto", "off", "force"] = Field(
        default="auto",
        description="PDF 复杂表格兜底：auto=检测到复杂表格时改用结构化后端；"
        "force=始终用结构化后端；off=关闭",
    )


class ExtractResult(BaseModel):
    """Normalized extraction result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    extractor: str
    document: StructuredDocument


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _candidate_backends(requested: str, suffix: str) -> List[str]:
    """Backend candidates in try-order; explicit requests yield exactly one.

    ``auto`` walks ``_AUTO_ORDER``: an installed optional backend that fails
    at extraction time falls through to the next candidate (eventually
    ``light``), so one broken optional dependency cannot fail the whole
    extraction. Explicit requests never fall back — the caller asked for that
    specific backend.
    """
    if requested != "auto":
        if requested not in list_extractors():
            raise OfficeParseError(f"extractor_unknown: {requested}")
        if not extractor_available(requested):
            raise OfficeParseError(
                f"extractor_unavailable: {requested}（未安装对应可选依赖）"
            )
        return [requested]
    candidates: List[str] = []
    for name in _AUTO_ORDER:
        if name in candidates or not extractor_available(name):
            continue
        try:
            extractor = get_extractor(name)
        except Exception:  # noqa: BLE001 — 探测后实例化失败按不可用处理
            continue
        if extractor.supports(suffix):
            candidates.append(name)
    if not candidates:
        raise OfficeParseError(f"extractor_unavailable: 没有支持 {suffix} 的解析后端")
    return candidates


def _try_table_fallback(
    source: Path, suffix: str
) -> Tuple[Optional[StructuredDocument], Optional[Dict[str, str]]]:
    """Re-parse a document with the structured backend for complex tables.

    Returns ``(document, note)``. ``document`` is ``None`` when the
    structured backend is unavailable or failed — the caller then keeps the
    original light-backend result. ``note`` is always present so the user
    can see why the result may still be lossy.
    """
    if not extractor_available(_TABLE_FALLBACK_BACKEND):
        return None, {
            "code": "table_fallback_unavailable",
            "message": "检测到复杂表格，但结构化后端未安装，已保留轻量解析结果",
        }
    try:
        extractor = get_extractor(_TABLE_FALLBACK_BACKEND)
        if not extractor.supports(suffix):
            return None, {
                "code": "table_fallback_unavailable",
                "message": "结构化后端不支持该文档类型，已保留轻量解析结果",
            }
        return extractor.extract(source), {
            "code": "table_fallback_docling",
            "message": "检测到复杂表格，已改用结构化后端重新解析",
        }
    except Exception as exc:  # noqa: BLE001 — 兜底失败保留原结果，不让整次提取失败
        logger.warning("table fallback failed for %s: %s", source, exc)
        return None, {
            "code": "table_fallback_failed",
            "message": "结构化后端兜底解析失败，已保留轻量解析结果",
        }


def _needs_table_fallback(request: ExtractRequest, document: StructuredDocument) -> bool:
    """Whether the PDF result should be re-parsed with the structured backend."""
    if request.table_fallback == "off":
        return False
    if request.table_fallback == "force":
        return True
    return bool(assess_table_complexity(document.table_diagnostics))


def extract_document(request: ExtractRequest) -> ExtractResult:
    """Extract a managed document into StructuredDocument."""
    workspace = validate_workspace(Path(request.workspace_path))
    source = resolve_within(workspace, Path(request.file_path))
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise OfficeParseError(f"不支持的文档类型: {suffix}")
    if source.stat().st_size > MAX_EXTRACT_BYTES:
        raise OfficeSizeLimitError(
            source.stat().st_size, MAX_EXTRACT_BYTES, file_path=source
        )

    backends = _candidate_backends(request.backend, suffix)
    document: Optional[StructuredDocument] = None
    fallback_warnings: List[Dict[str, str]] = []
    used_backend = backends[0]
    for position, name in enumerate(backends):
        extractor = get_extractor(name)
        if not extractor.supports(suffix):
            raise OfficeParseError(
                f"extractor_unsupported: {name} 不支持 {suffix}"
            )
        try:
            document = extractor.extract(source)
        except Exception as exc:  # noqa: BLE001 — 显式后端归一映射；auto 回退下一候选
            if position == len(backends) - 1:
                if isinstance(exc, OfficeParseError):
                    raise
                raise OfficeParseError(f"解析失败: {exc}", file_path=source) from exc
            next_name = backends[position + 1]
            fallback_warnings.append(
                {
                    "code": "extractor_fallback",
                    "message": f"{name} 解析失败（{exc}），已回退到 {next_name}",
                }
            )
            logger.warning(
                "extractor %s failed on %s: %s; falling back to %s",
                name,
                source,
                exc,
                next_name,
            )
            continue
        used_backend = name
        break
    if document is None:
        raise OfficeParseError("解析失败: 无可用解析后端", file_path=source)

    warnings: List[Dict[str, str]] = fallback_warnings + list(document.warnings)
    # M6b: PDF 复杂表格兜底 —— light 后端只按矢量线框抽表，合并单元格 /
    # 无边框表格会丢结构；此时改用结构化后端重解析一次。
    if (
        suffix == ".pdf"
        and used_backend != _TABLE_FALLBACK_BACKEND
        and _needs_table_fallback(request, document)
    ):
        fallback_document, fallback_note = _try_table_fallback(source, suffix)
        if fallback_document is not None:
            warnings.extend(fallback_document.warnings)
            document = fallback_document
            used_backend = _TABLE_FALLBACK_BACKEND
        if fallback_note:
            warnings.append(fallback_note)
    markdown = document.markdown
    if len(markdown) > request.max_chars:
        markdown = markdown[: request.max_chars]
        warnings.append(
            {
                "code": "markdown_truncated",
                "message": f"提取文本超过 {request.max_chars} 字符，已截断",
            }
        )
    document = document.model_copy(
        update={
            "source_path": _rel(source, workspace),
            "markdown": markdown,
            "warnings": warnings,
        }
    )
    return ExtractResult(ok=True, extractor=used_backend, document=document)
