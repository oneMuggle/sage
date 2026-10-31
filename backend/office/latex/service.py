"""Workspace-safe LaTeX preview service.

This module is the only entry point used by REST/tool layers. It enforces
workspace boundaries and size limits, then delegates to the dependency-free
parser. It never executes TeX.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.path_safety import is_within, resolve_within

from .audit import audit_latex_file
from .compile import compile_latex, detect_tools
from .diff import latexdiff_files
from .filler import fill_latex_template
from .parser import LatexLimits, parse_latex_project
from .template import analyze_latex_template

#: Raw source returned alongside the structured preview (characters).
MAX_SOURCE_CHARS = 512 * 1024
#: Hard cap for a single main .tex file.
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024


def _relative_to(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def read_latex_file(
    file_path: Path,
    *,
    workspace: Path,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Parse a ``.tex`` file inside ``workspace`` and return a preview payload.

    The payload is JSON-serializable and intentionally shaped like the other
    artifact/workspace previews: ``{ok, kind, content, structured, truncated}``.
    """
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise OfficeParseError("工作区目录不存在")
    source = Path(file_path)
    if not source.exists():
        raise OfficeFileNotFoundError(source)
    if not source.is_file():
        raise OfficeParseError("LaTeX 路径不是文件")
    if source.suffix.lower() not in (".tex", ".ltx"):
        raise OfficeParseError("仅支持 .tex 文件预览")
    try:
        resolved = resolve_within(workspace_path, source)
    except OfficePathError:
        raise
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise OfficeParseError("无法读取 LaTeX 文件大小") from exc
    if size > max_bytes:
        raise OfficeSizeLimitError(size, max_bytes)
    try:
        raw = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise OfficeParseError("读取 LaTeX 文件失败") from exc

    doc = parse_latex_project(
        resolved,
        root=workspace_path,
        limits=limits,
    )
    structured = doc.to_dict()
    truncated = len(raw) > MAX_SOURCE_CHARS
    return {
        "ok": True,
        "kind": "latex",
        "source_path": _relative_to(resolved, workspace_path),
        "content": raw[:MAX_SOURCE_CHARS],
        "structured": structured,
        "truncated": truncated,
    }


def read_latex_path(
    file_path: Path, *, root: Optional[Path] = None
) -> Dict[str, Any]:
    """Path-only helper for artifact/workspace preview readers.

    ``root`` defaults to the file's parent directory. Callers that know the
    workspace root (workspace preview route) should pass it so include
    resolution cannot escape the workspace.
    """
    path = Path(file_path)
    root_path = Path(root) if root is not None else path.parent
    return read_latex_file(path, workspace=root_path)


def is_latex_path(path: Path) -> bool:
    return path.suffix.lower() in (".tex", ".ltx")


def analyze_latex_template_file(
    file_path: Path,
    *,
    workspace: Path,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Workspace-safe template profile extraction."""
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise OfficeParseError("工作区目录不存在")
    source = Path(file_path)
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in (".tex", ".ltx"):
        raise OfficeParseError("仅支持 .tex 模板")
    resolved = resolve_within(workspace_path, source)
    size = resolved.stat().st_size
    if size > max_bytes:
        raise OfficeSizeLimitError(size, max_bytes)
    profile = analyze_latex_template(
        resolved,
        root=workspace_path,
        limits=limits,
    )
    payload = profile.to_dict()
    payload["ok"] = True
    payload["kind"] = "latex-template"
    return payload


def fill_latex_template_file(
    template_path: Path,
    data: Dict[str, Any],
    output_filename: str,
    *,
    workspace: Path,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Workspace-safe template fill (writes a new .tex, never the template)."""
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise OfficeParseError("工作区目录不存在")
    template = Path(template_path)
    if not template.is_file():
        raise OfficeFileNotFoundError(template)
    resolved = resolve_within(workspace_path, template)
    size = resolved.stat().st_size
    if size > max_bytes:
        raise OfficeSizeLimitError(size, max_bytes)
    return fill_latex_template(
        resolved,
        data,
        output_filename,
        root=workspace_path,
        limits=limits,
    )


def audit_latex_file_service(
    file_path: Path,
    *,
    workspace: Path,
    required_sections: Optional[List[str]] = None,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Workspace-safe deterministic LaTeX audit."""
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise OfficeParseError("工作区目录不存在")
    source = Path(file_path)
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in (".tex", ".ltx"):
        raise OfficeParseError("仅支持 .tex 审校")
    resolved = resolve_within(workspace_path, source)
    size = resolved.stat().st_size
    if size > max_bytes:
        raise OfficeSizeLimitError(size, max_bytes)
    return audit_latex_file(
        resolved,
        root=workspace_path,
        required_sections=required_sections,
        limits=limits,
    )


def compile_latex_file(
    file_path: Path,
    *,
    workspace: Path,
    output_filename: Optional[str] = None,
    engine: Optional[str] = None,
    timeout_s: int = 60,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Workspace-safe optional TeX compile."""
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise OfficeParseError("工作区目录不存在")
    source = Path(file_path)
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    resolved = resolve_within(workspace_path, source)
    size = resolved.stat().st_size
    if size > max_bytes:
        raise OfficeSizeLimitError(size, max_bytes)
    return compile_latex(
        resolved,
        root=workspace_path,
        output_filename=output_filename,
        engine=engine,
        timeout_s=timeout_s,
        limits=limits,
    )


def latexdiff_files_service(
    original_path: Path,
    revised_path: Path,
    *,
    workspace: Path,
    output_filename: str = "",
    compile_pdf: bool = False,
    engine: Optional[str] = None,
    timeout_s: int = 60,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Workspace-safe latexdiff (optional PDF compile)."""
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise OfficeParseError("工作区目录不存在")
    for path in (original_path, revised_path):
        source = Path(path)
        if not source.is_file():
            raise OfficeFileNotFoundError(source)
        resolved = resolve_within(workspace_path, source)
        if resolved.stat().st_size > max_bytes:
            raise OfficeSizeLimitError(resolved.stat().st_size, max_bytes)
    return latexdiff_files(
        Path(original_path),
        Path(revised_path),
        root=workspace_path,
        output_filename=output_filename,
        compile_pdf=compile_pdf,
        engine=engine,
        timeout_s=timeout_s,
        limits=limits,
    )


def latex_capabilities() -> Dict[str, Any]:
    """Return available TeX engines and latexdiff."""
    return detect_tools()


def is_within_root(path: Path, root: Path) -> bool:
    try:
        return is_within(Path(root).resolve(), Path(path).resolve())
    except OSError:
        return False


def safe_relative(path: Path, root: Path) -> str:
    try:
        return os.path.relpath(str(Path(path).resolve()), str(Path(root).resolve()))
    except (OSError, ValueError):
        return Path(path).name


__all__ = [
    "DEFAULT_MAX_FILE_BYTES",
    "MAX_SOURCE_CHARS",
    "analyze_latex_template_file",
    "audit_latex_file_service",
    "compile_latex_file",
    "fill_latex_template_file",
    "is_latex_path",
    "is_within_root",
    "latex_capabilities",
    "latexdiff_files_service",
    "read_latex_file",
    "read_latex_path",
    "safe_relative",
]
