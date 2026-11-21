"""Word tracked changes (M3): read revisions and accept/reject them.

The write side lives in ``word_revision_writer``; this module is the
read/resolve counterpart.  ``python-docx``'s ``paragraph.text`` excludes
``w:ins`` / ``w:del`` content, so revision inspection is done at the OOXML
level.

Scope note (M3a): body paragraphs (``document.paragraphs``) only —
table-cell revisions and deleted-paragraph-mark merging are follow-ups.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from .models import WordTrackedChange
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

MAX_DOCX_BYTES = 50 * 1024 * 1024

__all__ = [
    "WordTrackedChange",
    "WordTrackedChangesReadRequest",
    "WordTrackedChangesResolveRequest",
    "WordTrackedChangesResolveResult",
    "WordTrackedChangesResult",
    "extract_tracked_changes",
    "read_word_tracked_changes",
    "resolve_word_tracked_changes",
]


class WordTrackedChangesReadRequest(BaseModel):
    """POST /office/word/tracked-changes request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class WordTrackedChangesResult(BaseModel):
    """POST /office/word/tracked-changes result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    source_path: str
    changes: List[WordTrackedChange] = Field(default_factory=list)
    warnings: List[Dict[str, str]] = Field(default_factory=list)


class WordTrackedChangesResolveRequest(BaseModel):
    """POST /office/word/tracked-changes/resolve request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    mode: Literal["accept", "reject"]
    output_filename: Optional[str] = None
    overwrite: bool = False


class WordTrackedChangesResolveResult(BaseModel):
    """Result of accept/reject resolution."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    mode: Literal["accept", "reject"]
    source_path: str
    output_path: str
    overwritten: bool = False
    insertions: int = 0
    deletions: int = 0
    warnings: List[Dict[str, str]] = Field(default_factory=list)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def extract_tracked_changes(document: Any) -> List[WordTrackedChange]:
    """Collect w:ins / w:del elements from all body paragraphs (tables included).

    Paragraph indices follow OOXML body order, matching the resolve scope so
    "read says no revisions" can never disagree with accept/reject.
    """
    from docx.oxml.ns import qn  # noqa: PLC0415

    changes: List[WordTrackedChange] = []
    body = document.element.body
    for paragraph_index, paragraph_element in enumerate(body.iter(qn("w:p"))):
        for kind, tag, text_tag in (
            ("insert", "w:ins", "w:t"),
            ("delete", "w:del", "w:delText"),
        ):
            for element in paragraph_element.iter(qn(tag)):
                text = "".join(
                    node.text or "" for node in element.iter(qn(text_tag))
                )
                if not text:
                    continue
                changes.append(
                    WordTrackedChange(
                        kind=kind,
                        text=text,
                        author=element.get(qn("w:author")) or None,
                        date=element.get(qn("w:date")) or None,
                        paragraph_index=paragraph_index,
                    )
                )
    return changes


def _load_docx(file_path: Path) -> Any:
    try:
        from docx import Document
    except Exception as exc:  # noqa: BLE001 — python-docx 缺失按解析失败处理
        raise OfficeParseError(f"python-docx 不可用: {exc}") from exc
    try:
        return Document(str(file_path))
    except Exception as exc:  # noqa: BLE001 — 统一映射解析失败
        raise OfficeParseError(f"Failed to parse DOCX: {exc}", file_path=file_path) from exc


def _validate_source(workspace_path: str, file_path: str) -> tuple:
    workspace = validate_workspace(Path(workspace_path))
    source = resolve_within(workspace, Path(file_path))
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() != ".docx":
        raise OfficeParseError("修订读取/接受拒绝仅支持 .docx")
    if source.stat().st_size > MAX_DOCX_BYTES:
        raise OfficeSizeLimitError(
            source.stat().st_size, MAX_DOCX_BYTES, file_path=source
        )
    return workspace, source


def read_word_tracked_changes(workspace_path: str, file_path: str) -> WordTrackedChangesResult:
    """Read tracked changes from a managed .docx."""
    workspace, source = _validate_source(workspace_path, file_path)
    document = _load_docx(source)
    changes = extract_tracked_changes(document)
    warnings: List[Dict[str, str]] = []
    if not changes:
        warnings.append(
            {"code": "no_tracked_changes", "message": "文档没有待处理的修订痕迹"}
        )
    return WordTrackedChangesResult(
        ok=True,
        source_path=_rel(source, workspace),
        changes=changes,
        warnings=warnings,
    )


def _unwrap(element: Any) -> None:
    parent = element.getparent()
    if parent is None:
        return
    index = parent.index(element)
    for child in list(element):
        parent.insert(index, child)
        index += 1
    parent.remove(element)


def _remove(element: Any) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _reject_deletion(element: Any) -> None:
    """Turn a w:del back into normal runs (delText→t, drop rPr/w:del)."""
    from docx.oxml.ns import qn  # noqa: PLC0415

    for node in list(element.iter(qn("w:delText"))):
        node.tag = qn("w:t")
    for run in element.iter(qn("w:r")):
        run_properties = run.find(qn("w:rPr"))
        if run_properties is None:
            continue
        for marker in run_properties.findall(qn("w:del")):
            run_properties.remove(marker)


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


def _save_document(document: Any, target: Path, *, overwrite_source: bool) -> None:
    if not overwrite_source:
        try:
            document.save(str(target))
        except OSError as exc:
            raise OfficeParseError(f"保存文档失败: {exc}", file_path=target) from exc
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".m3-tmp", dir=str(target.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        document.save(str(temporary))
        for delay in (0.0, 0.1, 0.3):
            if delay:
                import time  # noqa: PLC0415

                time.sleep(delay)
            try:
                temporary.replace(target)
                return
            except PermissionError:
                continue
        raise OfficeParseError("原子替换失败（文件可能被占用）", file_path=target)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            logger.warning("failed to clean temporary file %s", temporary)


def resolve_word_tracked_changes(
    request: WordTrackedChangesResolveRequest,
) -> WordTrackedChangesResolveResult:
    """Accept or reject all tracked changes, writing a resolved .docx."""
    workspace, source = _validate_source(request.workspace_path, request.file_path)
    document = _load_docx(source)
    body = document.element.body

    from docx.oxml.ns import qn  # noqa: PLC0415

    insertions = list(body.iter(qn("w:ins")))
    deletions = list(body.iter(qn("w:del")))
    insertion_count = 0
    deletion_count = 0

    if request.mode == "accept":
        for element in deletions:
            if element.getparent() is None:
                continue
            _remove(element)
            deletion_count += 1
        for element in insertions:
            if element.getparent() is None:
                continue
            _unwrap(element)
            insertion_count += 1
    else:
        for element in insertions:
            if element.getparent() is None:
                continue
            _remove(element)
            insertion_count += 1
        for element in deletions:
            if element.getparent() is None:
                continue
            _reject_deletion(element)
            _unwrap(element)
            deletion_count += 1

    warnings: List[Dict[str, str]] = []
    if insertion_count == 0 and deletion_count == 0:
        warnings.append(
            {"code": "no_tracked_changes", "message": "文档没有待处理的修订痕迹"}
        )

    overwritten = bool(request.overwrite)
    if overwritten:
        if request.output_filename:
            raise OfficeParseError("overwrite=true 时不能指定 output_filename")
        target = source
    else:
        default_name = (
            f"{source.stem}-accepted.docx"
            if request.mode == "accept"
            else f"{source.stem}-rejected.docx"
        )
        name = _validate_output_name(request.output_filename or default_name)
        try:
            target = resolve_within(workspace, source.parent / name)
        except OfficePathError as exc:
            raise OfficeParseError("输出路径不在工作区内") from exc
        if target == source:
            raise OfficeParseError("输出文件不能覆盖源文件；如需覆盖请使用 overwrite=true")
        if target.exists():
            raise OfficeParseError("输出文件已存在，拒绝覆盖")

    _save_document(document, target, overwrite_source=overwritten)
    return WordTrackedChangesResolveResult(
        ok=True,
        mode=request.mode,
        source_path=_rel(source, workspace),
        output_path=_rel(target, workspace),
        overwritten=overwritten,
        insertions=insertion_count,
        deletions=deletion_count,
        warnings=warnings,
    )
