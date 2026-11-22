"""DOCX run coalescing (M5).

Word fragments visible text across many ``w:r`` runs (revision ids,
spell-check markers), so a phrase you can see is often not contiguous in
``document.xml``.  Merging adjacent identically-formatted runs makes
find/replace and text anchors reliable without changing rendering.

Only paragraph-direct runs with a single ``w:t`` are merged; runs with
tabs/breaks/fields are left untouched.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from ..path_safety import resolve_within
from ..storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = [
    "OoxmlMergeRunsRequest",
    "OoxmlMergeRunsResult",
    "merge_docx_runs",
]

MAX_DOCX_BYTES = 50 * 1024 * 1024
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


class OoxmlMergeRunsRequest(BaseModel):
    """POST /office/ooxml/merge-runs request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    output_filename: Optional[str] = None
    overwrite: bool = False


class OoxmlMergeRunsResult(BaseModel):
    """Merge result: how many runs were coalesced and where the file went."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    source_path: str
    output_path: str
    merged_runs: int = 0
    warnings: List[Dict[str, str]] = Field(default_factory=list)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _validate_output_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise OfficeParseError("output_filename 不能为空")
    if Path(value).is_absolute() or "/" in value or "\\" in value:
        raise OfficeParseError("output_filename 不能包含路径分隔符")
    if value in (".", ".."):
        raise OfficeParseError("output_filename 非法")
    if not value.lower().endswith(".docx"):
        raise OfficeParseError("output_filename 必须以 .docx 结尾")
    return value


def _run_text_element(run: Any, qn: Any) -> Optional[Any]:
    """Return the single w:t child if the run is mergeable, else None."""
    children = [child for child in run if child.tag != qn("w:rPr")]
    if len(children) != 1 or children[0].tag != qn("w:t"):
        return None
    return children[0]


def _rpr_signature(run: Any, qn: Any, etree: Any) -> bytes:
    rpr = run.find(qn("w:rPr"))
    if rpr is None:
        return b""
    return etree.tostring(rpr, with_tail=False)


def _save_document(document: Any, target: Path, *, overwrite_source: bool) -> None:
    if not overwrite_source:
        try:
            document.save(str(target))
        except OSError as exc:
            raise OfficeParseError(f"保存文档失败: {exc}", file_path=target) from exc
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".m5-tmp", dir=str(target.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        document.save(str(temporary))
        temporary.replace(target)
    except OSError as exc:
        raise OfficeParseError(f"原子替换失败: {exc}", file_path=target) from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                logger.debug("failed to clean %s", temporary)


def merge_docx_runs(request: OoxmlMergeRunsRequest) -> OoxmlMergeRunsResult:
    """Merge adjacent identically formatted runs in a managed .docx."""
    workspace = validate_workspace(Path(request.workspace_path))
    source = resolve_within(workspace, Path(request.file_path))
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() != ".docx":
        raise OfficeParseError("run 合并仅支持 .docx")
    if source.stat().st_size > MAX_DOCX_BYTES:
        raise OfficeSizeLimitError(
            source.stat().st_size, MAX_DOCX_BYTES, file_path=source
        )

    from docx import Document  # noqa: PLC0415
    from docx.oxml.ns import qn  # noqa: PLC0415
    from lxml import etree  # noqa: PLC0415

    try:
        document = Document(str(source))
    except Exception as exc:  # noqa: BLE001 — 统一映射解析失败
        raise OfficeParseError(f"Failed to parse DOCX: {exc}", file_path=source) from exc

    merged_runs = 0
    for paragraph in document.element.body.iter(qn("w:p")):
        previous_run = None
        previous_signature = None
        previous_text = None
        for run in list(paragraph.findall(qn("w:r"))):
            text_element = _run_text_element(run, qn)
            if text_element is None:
                previous_run = previous_signature = previous_text = None
                continue
            signature = _rpr_signature(run, qn, etree)
            if (
                previous_run is not None
                and previous_signature == signature
                and previous_text is not None
            ):
                previous_text.text = (previous_text.text or "") + (
                    text_element.text or ""
                )
                if previous_text.text != previous_text.text.strip():
                    previous_text.set(_XML_SPACE, "preserve")
                paragraph.remove(run)
                merged_runs += 1
                continue
            previous_run = run
            previous_signature = signature
            previous_text = text_element

    overwritten = bool(request.overwrite)
    if overwritten:
        if request.output_filename:
            raise OfficeParseError("overwrite=true 时不能指定 output_filename")
        target = source
    else:
        name = _validate_output_name(
            request.output_filename or f"{source.stem}-merged.docx"
        )
        try:
            target = resolve_within(workspace, source.parent / name)
        except OfficePathError as exc:
            raise OfficeParseError("输出路径不在工作区内") from exc
        if target == source:
            raise OfficeParseError("输出文件不能覆盖源文件；如需覆盖请使用 overwrite=true")
        if target.exists():
            raise OfficeParseError("输出文件已存在，拒绝覆盖")

    _save_document(document, target, overwrite_source=overwritten)
    return OoxmlMergeRunsResult(
        ok=True,
        source_path=_rel(source, workspace),
        output_path=_rel(target, workspace),
        merged_runs=merged_runs,
    )
