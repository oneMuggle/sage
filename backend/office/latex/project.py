"""Safe LaTeX project zip import (extract + main-file detection).

Extraction is deliberately conservative: only document/resource suffixes are
written, every member path is validated, archives are expanded into a temporary
directory inside the workspace and atomically renamed into place. Nothing
inside the archive is executed or compiled.
"""

from __future__ import annotations

import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.path_safety import is_within, resolve_within

_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_MAX_FILE_BYTES = 50 * 1024 * 1024
_MAX_MEMBERS = 2000
_MAX_RATIO = 200
_RATIO_MIN_BYTES = 10 * 1024 * 1024

_ALLOWED_SUFFIXES = {
    ".tex",
    ".ltx",
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
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".csv",
    ".txt",
    ".md",
}
_SKIP_PARTS = {
    "__MACOSX",
    ".DS_Store",
    "Thumbs.db",
    ".git",
    "node_modules",
    ".venv",
    "venv",
}
_MAIN_NAMES = (
    "main.tex",
    "paper.tex",
    "document.tex",
    "template.tex",
    "sample.tex",
    "main.ltx",
    "paper.ltx",
)
_MAIN_SCAN_BYTES = 256 * 1024
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _validate_part(part: str, original: str) -> None:
    if ":" in part:
        raise OfficeParseError(f"zip 包含非法路径片段: {original}")
    if part.endswith((".", " ")):
        raise OfficeParseError(f"zip 包含 Windows 非法尾随字符: {original}")
    if any(ord(ch) < 32 for ch in part):
        raise OfficeParseError(f"zip 包含控制字符: {original!r}")
    stem = part.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise OfficeParseError(f"zip 包含 Windows 保留名: {original}")


def _safe_member_name(name: str) -> Optional[str]:
    if not name or name.startswith("/") or name.startswith("\\"):
        raise OfficeParseError(f"zip 包含绝对路径: {name}")
    if _DRIVE_RE.match(name):
        raise OfficeParseError(f"zip 包含盘符路径: {name}")
    normalized = name.replace("\\", "/")
    parts: List[str] = []
    for part in PurePosixPath(normalized).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise OfficeParseError(f"zip 包含路径穿越: {name}")
        if part in _SKIP_PARTS:
            return None
        _validate_part(part, name)
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _is_encrypted(info: zipfile.ZipInfo) -> bool:
    return bool(info.flag_bits & 0x1)


def _contains_documentclass(data: bytes) -> bool:
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        if "\\documentclass" in line:
            return True
    return False


def detect_main_tex(root: Path) -> Tuple[Optional[Path], List[Path]]:
    """Return (preferred main file, all candidates containing ``\\documentclass``)."""
    candidates: List[Path] = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in (".tex", ".ltx"):
            continue
        try:
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()[:_MAIN_SCAN_BYTES]
        except OSError:
            continue
        if _contains_documentclass(data):
            candidates.append(path)
    if not candidates:
        return None, []
    candidates.sort(key=lambda item: (len(item.parts), str(item)))
    for name in _MAIN_NAMES:
        for path in candidates:
            if path.name.lower() == name:
                return path, candidates
    return candidates[0], candidates


def _validate_zip_path(zip_path: Path, workspace: Path) -> Path:
    source = Path(zip_path)
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() != ".zip":
        raise OfficeParseError("仅支持 .zip 项目包")
    try:
        resolved = source.resolve()
    except OSError as exc:
        raise OfficeParseError("无法解析 zip 路径") from exc
    if not is_within(workspace, resolved):
        raise OfficePathError("zip 文件不在工作区内", file_path=source)
    size = resolved.stat().st_size
    if size > _MAX_ARCHIVE_BYTES:
        raise OfficeSizeLimitError(size, _MAX_ARCHIVE_BYTES)
    return resolved


def _output_dir(workspace: Path, name: Optional[str], zip_path: Path) -> Path:
    candidate = (name or "").strip() or f"latex-{zip_path.stem}"
    if candidate in (".", "..") or "/" in candidate or "\\" in candidate:
        raise OfficeParseError("output_dir_name 不能包含路径分隔符")
    if Path(candidate).is_absolute():
        raise OfficeParseError("output_dir_name 不能是绝对路径")
    _validate_part(candidate, candidate)
    try:
        target = resolve_within(workspace, workspace / candidate)
    except OfficePathError as exc:
        raise OfficeParseError("输出目录不在工作区内") from exc
    if target == workspace:
        raise OfficeParseError("输出目录不能是工作区根")
    if target.exists():
        raise OfficeParseError("输出目录已存在，拒绝覆盖")
    return target


def _copy_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as src, dest.open("wb") as out:
        shutil.copyfileobj(src, out)


def extract_latex_project_zip(
    zip_path: Path,
    *,
    workspace: Path,
    output_dir_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Safely extract a LaTeX project zip into a new workspace directory."""
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        raise OfficeParseError("工作区目录不存在")
    source = _validate_zip_path(Path(zip_path), workspace_path)
    target = _output_dir(workspace_path, output_dir_name, source)

    temp_dir = Path(
        tempfile.mkdtemp(prefix=".latex-import-", dir=str(workspace_path))
    )
    warnings: List[Dict[str, str]] = []
    files_count = 0
    bytes_written = 0
    seen_names: Dict[str, str] = {}
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_MEMBERS:
                raise OfficeParseError(
                    f"zip 条目数超过上限（{len(infos)} > {_MAX_MEMBERS}）"
                )
            for info in infos:
                if info.is_dir():
                    continue
                if _is_encrypted(info):
                    raise OfficeParseError("不支持加密 zip")
                if _is_symlink(info):
                    raise OfficeParseError("zip 包含符号链接条目")
                safe_name = _safe_member_name(info.filename)
                if safe_name is None:
                    continue
                key = safe_name.lower()
                if key in seen_names:
                    raise OfficeParseError(f"zip 包含重复或大小写冲突条目: {safe_name}")
                seen_names[key] = safe_name
                suffix = PurePosixPath(safe_name).suffix.lower()
                if suffix not in _ALLOWED_SUFFIXES:
                    warnings.append(
                        {
                            "code": "unsupported_file_skipped",
                            "message": f"跳过非文档资源: {safe_name}",
                            "path": safe_name,
                        }
                    )
                    continue
                if info.file_size > _MAX_FILE_BYTES:
                    raise OfficeParseError(f"zip 内单文件超过上限: {safe_name}")
                bytes_written += info.file_size
                if bytes_written > _MAX_UNCOMPRESSED_BYTES:
                    raise OfficeParseError("zip 解压总量超过上限")
                if (
                    info.compress_size > 0
                    and info.file_size > _RATIO_MIN_BYTES
                    and info.file_size / info.compress_size > _MAX_RATIO
                ):
                    raise OfficeParseError(
                        f"zip 压缩比异常（疑似 zip bomb）: {safe_name}"
                    )
                destination = temp_dir / safe_name
                _copy_member(archive, info, destination)
                files_count += 1
    except OfficeParseError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise OfficeParseError(f"zip 解压失败: {exc}") from exc

    main, candidates = detect_main_tex(temp_dir)
    if main is None:
        warnings.append(
            {
                "code": "no_main_tex",
                "message": "未找到包含 \\documentclass 的 .tex 主文件",
            }
        )
    try:
        temp_dir.replace(target)
    except OSError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise OfficeParseError(f"项目目录落盘失败: {exc}") from exc

    def rel(path: Optional[Path]) -> Optional[str]:
        if path is None:
            return None
        return (Path(target.name) / path.relative_to(temp_dir)).as_posix()

    return {
        "ok": True,
        "project_dir": target.relative_to(workspace_path).as_posix(),
        "main_file": rel(main),
        "main_candidates": [rel(path) for path in candidates],
        "files_count": files_count,
        "bytes_written": bytes_written,
        "warnings": warnings,
    }


__all__ = ["detect_main_tex", "extract_latex_project_zip"]
