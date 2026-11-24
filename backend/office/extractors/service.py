"""Extraction service (M6b): validate, select backend, normalize output."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Literal, Optional

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

logger = logging.getLogger(__name__)

__all__ = ["ExtractRequest", "ExtractResult", "extract_document"]

MAX_EXTRACT_BYTES = 200 * 1024 * 1024
_SUPPORTED_SUFFIXES = (".docx", ".xlsx", ".pptx", ".pdf", ".csv", ".md", ".html", ".txt")
_AUTO_ORDER = ("docling", "markitdown", "light")


class ExtractRequest(BaseModel):
    """POST /office/extract request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    backend: Literal["auto", "light", "markitdown", "docling"] = Field(
        default="auto", description="auto 优先可选后端，缺失时回退 light"
    )
    max_chars: int = Field(default=200_000, ge=1000, le=2_000_000)


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
