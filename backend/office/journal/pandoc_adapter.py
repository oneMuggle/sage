"""`.doc` (OLE2/CFBF) → `.docx` (OOXML) 透明转换层。

- 仅在 .doc 输入时调用 pandoc 子进程；.docx 透传；
- subprocess.run([...], shell=False, timeout=30, capture_output=True)；
- 按 sha256(ppt) 缓存到 <cache_dir>/<sha256>.docx；
- 缺失 pandoc → JournalPandocError("pandoc 未安装，请 apt install pandoc")。
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from backend.office.journal.errors import JournalPandocError


_TIMEOUT_SECONDS = 30


def is_pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def cache_key_for(path: Path) -> str:
    """sha256 of path contents (hex, 64 chars)。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def convert_doc_to_docx(
    input_path: Path, cache_dir: Path, *, timeout: int = _TIMEOUT_SECONDS
) -> Path:
    """转换 .doc → .docx；同 sha256 缓存命中直接返回缓存路径。"""
    if not input_path.exists():
        raise JournalPandocError(f"输入文件不存在: {input_path}")

    # .docx 透传，不写缓存
    if input_path.suffix.lower() == ".docx":
        return input_path

    if input_path.suffix.lower() != ".doc":
        raise JournalPandocError(f"不支持的扩展名: {input_path.suffix}")

    if not is_pandoc_available():
        raise JournalPandocError("pandoc 未安装，请运行 `apt install pandoc` 后重试")

    cache_dir.mkdir(parents=True, exist_ok=True)
    sha = cache_key_for(input_path)
    cached = cache_dir / f"{sha}.docx"
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    # 落临时名 + 原子 rename
    tmp_out = cache_dir / f".tmp-{sha}.docx"
    try:
        result = subprocess.run(
            [
                "pandoc",
                "--from",
                "doc",
                "--to",
                "docx",
                "--output",
                str(tmp_out),
                str(input_path),
            ],
            shell=False,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        tmp_out.unlink(missing_ok=True)
        raise JournalPandocError(f"pandoc 超时（>{timeout}s）") from exc
    except OSError as exc:
        tmp_out.unlink(missing_ok=True)
        raise JournalPandocError(f"pandoc 启动失败: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        tmp_out.unlink(missing_ok=True)
        raise JournalPandocError(
            f"pandoc 转换失败 (exit {result.returncode}): {stderr}"
        )

    if not tmp_out.exists() or tmp_out.stat().st_size == 0:
        tmp_out.unlink(missing_ok=True)
        raise JournalPandocError("pandoc 输出文件为空")

    tmp_out.replace(cached)
    return cached


__all__ = ["is_pandoc_available", "cache_key_for", "convert_doc_to_docx"]
