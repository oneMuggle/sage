"""SKILL.md 安全相关工具。

- ``validate_base_dir``: 防止 SKILL.md body 内 ``{baseDir}`` 占位符被替换时指到
  允许根目录之外 (路径遍历防御)。
- ``sanitize_for_logging``: 控制字符剥离 + 长度截断, 避免任意 body 内容泄漏
  到日志造成日志注入或不可控展开。

设计要点
--------

- 镜像 Rust 版 ``validate_wiki_path`` 的思路
  (``archive/src-tauri-2026-06-13-main-migration/src/wiki/util.rs:9-30``)
  但用 Python 表达: resolve 双方到绝对路径, ``is_relative_to`` 校验包含关系。
- ``SkillMdSecurityError`` 独立异常类型, 方便上层 (loader) 区分安全错误与
  普通的 ``SkillMdParseError``。
"""

from __future__ import annotations
from typing import List

import re
from pathlib import Path

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class SkillMdSecurityError(Exception):
    """SKILL.md 路径安全校验失败。"""


def validate_base_dir(base_dir: Path, allowed_roots: List[Path]) -> Path:
    """断言 ``base_dir`` 落在任一 ``allowed_roots`` 内, 返回 resolve 后的绝对路径。

    Args:
        base_dir: 待校验的目录(通常是 SKILL.md 所在目录)。
        allowed_roots: 允许的根目录列表(例如 ``~/.sage/skills``)。

    Returns:
        resolve 后的绝对 ``Path``。

    Raises:
        SkillMdSecurityError: ``base_dir`` 不在任一允许根下, 或 allowed_roots 为空。
    """
    if not allowed_roots:
        raise SkillMdSecurityError("no allowed_roots provided")

    try:
        resolved_base = base_dir.resolve(strict=False)
    except OSError as exc:
        raise SkillMdSecurityError(f"cannot resolve base_dir {base_dir}: {exc}") from exc

    for root in allowed_roots:
        try:
            resolved_root = root.resolve(strict=False)
        except OSError:
            continue
        try:
            if resolved_base.is_relative_to(resolved_root):
                return resolved_base
        except AttributeError:
            # Python < 3.9 fallback (项目要求 3.8+, sage-backend 是 3.10, 通常不触发)
            try:
                resolved_base.relative_to(resolved_root)
                return resolved_base
            except ValueError:
                continue

    raise SkillMdSecurityError(
        f"base_dir {base_dir} is not under any allowed root " f"{[str(r) for r in allowed_roots]}"
    )


def sanitize_for_logging(text: str, max_len: int = 200) -> str:
    """剥离控制字符并截断, 用于把不可信 body 内容写入日志时脱敏。

    Args:
        text: 原始字符串。
        max_len: 截断上限, 默认 200 字符。

    Returns:
        安全的字符串: 控制字符已替换为 '?', 长度不超过 ``max_len``。
    """
    if not isinstance(text, str):
        text = str(text)
    cleaned = _CONTROL_CHARS_RE.sub("?", text)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + f"...(truncated, total {len(text)} chars)"
    return cleaned
