"""Optional external TeX compile adapter (no bundled engine, no shell escape)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
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
from .parser import LatexLimits

_ENGINE_CANDIDATES = ("latexmk", "xelatex", "lualatex", "pdflatex")
_COPY_SUFFIXES = {
    ".tex",
    ".cls",
    ".sty",
    ".bst",
    ".bib",
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".eps",
    ".svg",
    ".bmp",
    ".gif",
    ".webp",
}
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache"}
_MAX_COPY_FILES = 500
_MAX_COPY_BYTES = 50 * 1024 * 1024
_MAX_LOG_CHARS = 8000


def detect_engines() -> List[Dict[str, str]]:
    """Return available TeX engines (name + absolute path)."""
    engines: List[Dict[str, str]] = []
    for name in _ENGINE_CANDIDATES:
        path = shutil.which(name)
        if path:
            engines.append({"name": name, "path": path})
    return engines


def detect_tools() -> Dict[str, Any]:
    """Capability probe for compile/diff UI."""
    return {
        "engines": detect_engines(),
        "latexdiff": shutil.which("latexdiff"),
    }


def _select_engine(engine: Optional[str]) -> Optional[Dict[str, str]]:
    if engine:
        path = shutil.which(engine)
        if path:
            return {"name": engine, "path": path}
        return None
    engines = detect_engines()
    return engines[0] if engines else None


def _validate_source(file_path: Path, root: Path, limits: LatexLimits) -> Path:
    source = Path(file_path)
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in (".tex", ".ltx"):
        raise OfficeParseError("仅支持编译 .tex/.ltx")
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


def _output_path(
    source: Path, root: Path, output_filename: Optional[str], suffix: str
) -> Path:
    name = (output_filename or "").strip()
    if not name:
        name = source.stem + suffix
    if Path(name).is_absolute() or "/" in name or "\\" in name:
        raise OfficeParseError("output_filename 不能包含路径分隔符")
    if not name.lower().endswith(suffix):
        name += suffix
    try:
        target = resolve_within(root, source.parent / name)
    except OfficePathError as exc:
        raise OfficeParseError("输出路径不在工作区内") from exc
    if target == source:
        raise OfficeParseError("输出文件不能与源文件相同")
    if target.exists():
        raise OfficeParseError("输出文件已存在，拒绝覆盖")
    return target


def _copy_project(root: Path, temp_dir: Path) -> None:
    count = 0
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _COPY_SUFFIXES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        count += 1
        total += size
        if count > _MAX_COPY_FILES or total > _MAX_COPY_BYTES:
            raise OfficeParseError("LaTeX 项目文件数/体积超过编译上限")
        target = temp_dir / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _command(engine: Dict[str, str], main_name: str) -> List[str]:
    base = [
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
    ]
    if engine["name"] == "latexmk":
        if engine.get("variant") == "xelatex":
            return [engine["path"], "-xelatex", *base, main_name]
        if engine.get("variant") == "lualatex":
            return [engine["path"], "-lualatex", *base, main_name]
        return [engine["path"], "-pdf", *base, main_name]
    return [engine["path"], *base, main_name]


def compile_latex(  # noqa: PLR0911
    file_path: Path,
    *,
    root: Optional[Path] = None,
    output_filename: Optional[str] = None,
    engine: Optional[str] = None,
    timeout_s: int = 60,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Compile a .tex project to PDF with best-effort safety controls.

    Returns a structured result instead of raising for expected failures
    (no engine, audit gate, compile error, timeout). Path errors raise.
    """
    limits = limits or LatexLimits()
    root_path = (
        Path(root).resolve() if root is not None else Path(file_path).resolve().parent
    )
    if not root_path.is_dir():
        raise OfficeParseError("LaTeX 项目根目录不存在")
    source = _validate_source(Path(file_path), root_path, limits)
    target = _output_path(source, root_path, output_filename, ".pdf")

    audit = audit_latex_file(
        source,
        root=root_path,
        required_sections=[],
        limits=limits,
    )
    if not audit["ok"]:
        return {
            "ok": False,
            "code": "audit_failed",
            "message": "编译前审校未通过，请先修复 error 级问题（含危险命令）",
            "issues": audit["issues"],
        }

    selected = _select_engine(engine)
    if selected is None:
        return {
            "ok": False,
            "code": "no_engine",
            "message": "未检测到 TeX 引擎（latexmk/xelatex/lualatex/pdflatex）；请安装后重试",
            "available": detect_engines(),
        }
    if selected["name"] == "latexmk":
        # Resolve the actual driver so Chinese documents can use xelatex.
        for candidate in ("xelatex", "lualatex"):
            if shutil.which(candidate):
                selected = {
                    "name": "latexmk",
                    "path": selected["path"],
                    "variant": candidate,
                }
                break

    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="sage-latex-compile-") as tmp:
        temp_dir = Path(tmp)
        _copy_project(root_path, temp_dir)
        main_rel = source.relative_to(root_path)
        env = dict(os.environ)
        env.update(
            {
                "openin_any": "p",
                "openout_any": "p",
                "TEXMFHOME": str(temp_dir / "texmf"),
                "TEXMFVAR": str(temp_dir / "texmf-var"),
                "TEXMFCACHE": str(temp_dir / "texmf-cache"),
            }
        )
        cmd = _command(selected, str(main_rel))
        try:
            result = subprocess.run(
                cmd,
                cwd=str(temp_dir),
                env=env,
                shell=False,
                timeout=max(1, min(int(timeout_s), 600)),
                capture_output=True,
                text=True, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "code": "timeout",
                "message": f"编译超时（>{timeout_s}s）",
                "engine": selected["name"],
                "log_tail": (str(exc.stderr or "") + str(exc.stdout or ""))[
                    -_MAX_LOG_CHARS:
                ],
            }
        except OSError as exc:
            return {
                "ok": False,
                "code": "engine_start_failed",
                "message": f"无法启动 TeX 引擎: {exc}",
                "engine": selected["name"],
            }
        log = (result.stdout or "") + (result.stderr or "")
        pdf_candidate = temp_dir / main_rel.with_suffix(".pdf")
        if result.returncode != 0 or not pdf_candidate.is_file():
            return {
                "ok": False,
                "code": "compile_failed",
                "message": f"TeX 编译失败（exit {result.returncode}）",
                "engine": selected["name"],
                "returncode": result.returncode,
                "log_tail": log[-_MAX_LOG_CHARS:],
            }
        try:
            target.write_bytes(pdf_candidate.read_bytes())
        except OSError as exc:
            return {
                "ok": False,
                "code": "output_write_failed",
                "message": f"PDF 写入失败: {exc}",
                "engine": selected["name"],
            }
    return {
        "ok": True,
        "engine": selected["name"],
        "pdf_path": target.relative_to(root_path).as_posix(),
        "returncode": result.returncode,
        "log_tail": log[-_MAX_LOG_CHARS:],
        "duration_ms": int((time.monotonic() - start) * 1000),
    }


__all__ = ["compile_latex", "detect_engines", "detect_tools"]
