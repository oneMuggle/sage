"""下载文件的 magic + 题名校验（浏览器路径与 HTTP 路径共用）。

独立成模块是为了让 ``search.py`` 与 ``http_download.py`` 都能依赖它而不形成
循环导入：``search`` → ``http_download`` → ``pdf_check``。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List


def normalize_text(text: str) -> str:
    """去掉空白与标点，只留字母数字与汉字，用于题名比对。"""
    return re.sub(r"[\s\W_]+", "", text or "")


def validate_pdf(path: Path, expected_title: str, magic: str = "%PDF-") -> List[str]:
    """校验下载文件；返回错误列表，空列表表示通过。"""
    errors: List[str] = []
    if not path.is_file():
        return [f"下载文件不存在: {path}"]
    with path.open("rb") as handle:
        head = handle.read(len(magic))
    if head != magic.encode("ascii"):
        errors.append(f"文件头不是 {magic}")
    if expected_title:
        expected = normalize_text(expected_title)
        actual = normalize_text(path.stem)
        if expected and expected not in actual and actual not in expected:
            errors.append(f"文件名与题名不匹配: {path.name!r} vs {expected_title!r}")
    return errors
