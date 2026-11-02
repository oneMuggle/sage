"""latexdiff adapter for LaTeX redline source/PDF (optional external tool)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.path_safety import is_within, resolve_within

from .compile import compile_latex
from .parser import LatexLimits

_MAX_LOG_CHARS = 8000


def detect_latexdiff() -> Optional[str]:
    return shutil.which("latexdiff")


def _validate(path: Path, root: Path, limits: LatexLimits) -> Path:
    source = Path(path)
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in (".tex", ".ltx"):
        raise OfficeParseError("仅支持 .tex/.ltx 版本对比")
    try:
        resolved = source.resolve()
    except OSError as exc:
        raise OfficeParseError("无法解析 LaTeX 路径") from exc
    if not is_within(root, resolved):
        raise OfficePathError("LaTeX 文件不在项目目录内", file_path=source)
    size = resolved.stat().st_size
    if size > limits.max_file_bytes:
        raise OfficeSizeLimitError(size, limits.max_file_bytes)
    return resolved


def _output_path(original: Path, root: Path, output_filename: str) -> Path:
    name = (output_filename or "").strip()
    if not name:
        name = original.stem + "-diff.tex"
    if Path(name).is_absolute() or "/" in name or "\\" in name:
        raise OfficeParseError("output_filename 不能包含路径分隔符")
    if not name.lower().endswith(".tex"):
        name += ".tex"
    try:
        target = resolve_within(root, original.parent / name)
    except OfficePathError as exc:
        raise OfficeParseError("输出路径不在工作区内") from exc
    if target.exists():
        raise OfficeParseError("输出文件已存在，拒绝覆盖")
    return target


def latexdiff_files(
    original_path: Path,
    revised_path: Path,
    *,
    root: Optional[Path] = None,
    output_filename: str = "",
    compile_pdf: bool = False,
    engine: Optional[str] = None,
    timeout_s: int = 60,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Generate a latexdiff .tex (and optionally compile it to PDF)."""
    limits = limits or LatexLimits()
    root_path = (
        Path(root).resolve()
        if root is not None
        else Path(original_path).resolve().parent
    )
    if not root_path.is_dir():
        raise OfficeParseError("LaTeX 项目根目录不存在")
    original = _validate(Path(original_path), root_path, limits)
    revised = _validate(Path(revised_path), root_path, limits)
    target = _output_path(original, root_path, output_filename)

    tool = detect_latexdiff()
    if tool is None:
        return {
            "ok": False,
            "code": "no_latexdiff",
            "message": "未检测到 latexdiff；请安装 TeX 发行版或 latexdiff 后重试",
            "latexdiff_available": False,
        }

    original_rel = original.relative_to(root_path)
    revised_rel = revised.relative_to(root_path)
    try:
        result = subprocess.run(
            [tool, str(original_rel), str(revised_rel)],
            cwd=str(root_path),
            shell=False,
            timeout=max(1, min(int(timeout_s), 600)),
            capture_output=True,
            text=True, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "code": "timeout",
            "message": f"latexdiff 超时（>{timeout_s}s）",
            "log_tail": (str(exc.stderr or "") + str(exc.stdout or ""))[
                -_MAX_LOG_CHARS:
            ],
        }
    except OSError as exc:
        return {
            "ok": False,
            "code": "latexdiff_start_failed",
            "message": f"无法启动 latexdiff: {exc}",
        }

    log = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 or not (result.stdout or "").strip():
        return {
            "ok": False,
            "code": "diff_failed",
            "message": f"latexdiff 失败（exit {result.returncode}）",
            "returncode": result.returncode,
            "log_tail": log[-_MAX_LOG_CHARS:],
        }
    try:
        target.write_text(result.stdout, encoding="utf-8")
    except OSError as exc:
        return {
            "ok": False,
            "code": "output_write_failed",
            "message": f"diff.tex 写入失败: {exc}",
        }

    payload: Dict[str, Any] = {
        "ok": True,
        "diff_path": target.relative_to(root_path).as_posix(),
        "latexdiff_available": True,
    }
    if compile_pdf:
        compiled = compile_latex(
            target,
            root=root_path,
            output_filename=target.stem + ".pdf",
            engine=engine,
            timeout_s=timeout_s,
            limits=limits,
        )
        payload["compile"] = compiled
        if compiled.get("ok"):
            payload["pdf_path"] = compiled.get("pdf_path")
    return payload


__all__ = ["detect_latexdiff", "latexdiff_files"]
