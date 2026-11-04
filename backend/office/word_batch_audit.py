"""Batch Word audit + Markdown report (M5b).

Scans a workspace for .docx files (or takes an explicit list), audits each
with a rule pack, and aggregates counts into a JSON-friendly result plus an
optional Markdown report. Read-only; no files are written.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .errors import OfficeError, OfficeParseError, OfficePathError
from .path_safety import resolve_within
from .word_audit import audit_word_document
from .word_rulepack_models import (
    WordBatchAuditResult,
    WordBatchFileResult,
    WordBatchTotals,
    WordRulePack,
)

_SKIP_DIRS = {
    ".git",
    ".svn",
    ".sage",
    "node_modules",
    "__pycache__",
    "dist",
    "dist-electron",
    "build",
    ".venv",
    "venv",
}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def collect_docx_files(
    root: Path,
    *,
    file_paths: Optional[List[str]] = None,
    pattern: str = "**/*.docx",
    max_files: int = 20,
) -> List[Path]:
    """Collect workspace .docx files from an explicit list or a glob pattern."""
    workspace = Path(root).resolve()
    if max_files < 1:
        raise OfficeParseError("max_files 必须为正整数")
    if file_paths is not None:
        seen: set = set()
        files: List[Path] = []
        for raw in file_paths:
            candidate = Path(str(raw).strip())
            if not candidate.is_absolute():
                candidate = workspace / candidate
            try:
                resolved = resolve_within(workspace, candidate)
            except OfficePathError as exc:
                raise OfficeParseError(f"路径不在工作区内: {raw}") from exc
            if resolved.suffix.lower() != ".docx" or not resolved.is_file():
                continue
            key = resolved.resolve()
            if key in seen:
                continue
            seen.add(key)
            files.append(resolved)
            if len(files) >= max_files:
                break
        return files

    relative = Path(pattern)
    if not pattern or relative.is_absolute() or ".." in relative.parts:
        raise OfficeParseError("pattern 非法")
    files = []
    for path in sorted(workspace.glob(pattern), key=lambda item: item.as_posix()):
        if len(files) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() != ".docx":
            continue
        try:
            rel = path.resolve().relative_to(workspace)
        except ValueError:
            continue
        if any(part.startswith(".") or part in _SKIP_DIRS for part in rel.parts):
            continue
        files.append(path)
    return files


def _render_report(
    root: Path,
    pack: WordRulePack,
    totals: WordBatchTotals,
    files: List[WordBatchFileResult],
) -> str:
    lines = [
        "# Word 批量审校报告",
        "",
        f"- 工作区: `{root}`",
        f"- 规则包: `{pack.id}`（{pack.name}）",
        f"- 文件: {totals.files}（通过 {totals.ok_files} / 失败 {totals.failed_files}）",
        f"- 问题: {totals.error_count} 错误 / {totals.warning_count} 警告",
        "",
    ]
    for file in files:
        status = "✅" if file.ok else "❌"
        lines.append(f"## {status} {file.source_path}")
        if file.error:
            lines.append(f"- 失败: {file.error}")
        else:
            lines.append(f"- {file.error_count} 错误 / {file.warning_count} 警告")
        for issue in file.issues[:20]:
            lines.append(f"- [{issue.severity}] {issue.rule_id}: {issue.message}")
        if len(file.issues) > 20:
            lines.append(f"- …还有 {len(file.issues) - 20} 条问题")
        lines.append("")
    return "\n".join(lines)


def audit_word_batch(
    workspace_path: Path,
    rulepack: WordRulePack,
    *,
    file_paths: Optional[List[str]] = None,
    pattern: str = "**/*.docx",
    max_files: int = 20,
    max_size_bytes: int = 50 * 1024 * 1024,
    include_report: bool = True,
) -> WordBatchAuditResult:
    """Audit up to ``max_files`` workspace .docx files with ``rulepack``."""
    root = Path(workspace_path).resolve()
    if not root.is_dir():
        raise OfficeParseError("工作区目录不存在")
    files = collect_docx_files(
        root, file_paths=file_paths, pattern=pattern, max_files=max_files
    )
    results: List[WordBatchFileResult] = []
    totals = WordBatchTotals(files=len(files))
    for path in files:
        relative = _rel(path, root)
        if path.stat().st_size > max_size_bytes:
            results.append(
                WordBatchFileResult(
                    source_path=relative,
                    ok=False,
                    error="文件超过大小上限",
                )
            )
            totals.failed_files += 1
            continue
        try:
            audit = audit_word_document(path, rulepack, workspace_path=str(root))
        except OfficeError as exc:
            results.append(
                WordBatchFileResult(
                    source_path=relative,
                    ok=False,
                    error=str(exc),
                )
            )
            totals.failed_files += 1
            continue
        results.append(
            WordBatchFileResult(
                source_path=relative,
                ok=audit.ok,
                issue_count=audit.summary.issue_count,
                error_count=audit.summary.error_count,
                warning_count=audit.summary.warning_count,
                issues=audit.issues,
                warnings=audit.warnings,
            )
        )
        totals.ok_files += 1
        totals.issue_count += audit.summary.issue_count
        totals.error_count += audit.summary.error_count
        totals.warning_count += audit.summary.warning_count

    report = (
        _render_report(root, rulepack, totals, results) if include_report else None
    )
    return WordBatchAuditResult(
        ok=totals.failed_files == 0 and totals.error_count == 0,
        workspace_path=str(root),
        rule_pack_id=rulepack.id,
        totals=totals,
        files=results,
        report_markdown=report,
    )


__all__ = ["audit_word_batch", "collect_docx_files"]
