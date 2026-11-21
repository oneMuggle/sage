"""Cross-document comparison (M6b): unified diff over extracted markdown."""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficeSizeLimitError,
)
from .extractors.light import LightExtractor
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = [
    "CompareChange",
    "CompareRequest",
    "CompareResult",
    "CompareSummary",
    "compare_documents",
]

MAX_COMPARE_BYTES = 200 * 1024 * 1024
MAX_CHANGES = 500


class CompareRequest(BaseModel):
    """POST /office/compare request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    left_path: str
    right_path: str
    max_report_lines: int = Field(default=2000, ge=20, le=10_000)


class CompareChange(BaseModel):
    """One added/removed line from the unified diff."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["added", "removed"]
    text: str


class CompareSummary(BaseModel):
    """Line-level diff counts."""

    model_config = ConfigDict(extra="forbid")

    added: int = 0
    removed: int = 0
    unchanged: int = 0


class CompareResult(BaseModel):
    """Comparison result + ready-to-display Markdown report."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    format: str
    left_path: str
    right_path: str
    summary: CompareSummary = Field(default_factory=CompareSummary)
    changes: List[CompareChange] = Field(default_factory=list)
    report_markdown: str = ""
    warnings: List[Dict[str, str]] = Field(default_factory=list)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _validate(workspace_path: str, file_path: str) -> tuple:
    workspace = validate_workspace(Path(workspace_path))
    source = resolve_within(workspace, Path(file_path))
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in (".docx", ".xlsx", ".pptx", ".pdf", ".csv"):
        raise OfficeParseError(f"对比不支持的类型: {source.suffix}")
    if source.stat().st_size > MAX_COMPARE_BYTES:
        raise OfficeSizeLimitError(
            source.stat().st_size, MAX_COMPARE_BYTES, file_path=source
        )
    return workspace, source


def compare_documents(request: CompareRequest) -> CompareResult:
    """Compare two managed documents using the light extractor + unified diff."""
    workspace, left = _validate(request.workspace_path, request.left_path)
    _, right = _validate(request.workspace_path, request.right_path)

    extractor = LightExtractor()
    left_document = extractor.extract(left)
    right_document = extractor.extract(right)

    left_lines = left_document.markdown.splitlines()
    right_lines = right_document.markdown.splitlines()
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines, autojunk=False)
    unchanged = sum(block.size for block in matcher.get_matching_blocks())

    diff_lines = list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=_rel(left, workspace),
            tofile=_rel(right, workspace),
            lineterm="",
            n=2,
        )
    )

    warnings: List[Dict[str, str]] = []
    if not left_lines and not right_lines:
        warnings.append({"code": "no_text", "message": "两份文档均未提取到文本"})

    changes: List[CompareChange] = []
    added = removed = 0
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
            if len(changes) < MAX_CHANGES:
                changes.append(CompareChange(kind="added", text=line[1:]))
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
            if len(changes) < MAX_CHANGES:
                changes.append(CompareChange(kind="removed", text=line[1:]))
    if added + removed > MAX_CHANGES:
        warnings.append(
            {
                "code": "changes_truncated",
                "message": f"变更行超过 {MAX_CHANGES}，changes 列表已截断（report 仍完整）",
            }
        )

    report_lines = diff_lines
    if len(report_lines) > request.max_report_lines:
        report_lines = report_lines[: request.max_report_lines]
        warnings.append(
            {
                "code": "report_truncated",
                "message": f"报告超过 {request.max_report_lines} 行，已截断",
            }
        )

    left_label = _rel(left, workspace)
    right_label = _rel(right, workspace)
    report = "\n".join(
        [
            "## 文档对比",
            "",
            f"- 左：`{left_label}`",
            f"- 右：`{right_label}`",
            f"- 新增 **{added}** 行 / 删除 **{removed}** 行 / 相同 **{unchanged}** 行",
            "",
            "```diff",
            *report_lines,
            "```",
            "",
        ]
    )

    return CompareResult(
        ok=True,
        format=f"{left.suffix.lower()}→{right.suffix.lower()}",
        left_path=left_label,
        right_path=right_label,
        summary=CompareSummary(added=added, removed=removed, unchanged=unchanged),
        changes=changes,
        report_markdown=report,
        warnings=warnings,
    )
