# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""Markdown 规则文件的小节编辑与原子写（M4，2026-11-07）。

与 ``backend/api/global_rules_routes.py`` 的整文件 PUT 保持同一安全基线
（scanner level="all"、拒绝符号链接、同目录 mkstemp + os.replace），但
**不共用实现** —— 那个模块的测试 monkeypatch 了 ``mod.tempfile.mkstemp``，
抽公共函数会打断 ``test_write_error_maps_to_500``。
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Tuple

from backend.memory.safety import get_scanner
from backend.services.rules_registry import split_markdown_sections

MAX_RULE_CHARS = 2000
# 与 global_rules_routes.MAX_CONTENT_BYTES 同值；单文件写入后超限直接拒绝。
MAX_FILE_BYTES = 64 * 1024


class RuleValidationError(ValueError):
    """写入前校验失败；``status_code`` 供路由映射为 HTTP 状态。"""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def validate_rule_text(text: str) -> str:
    """去空白 → 长度上限 → 安全扫描（规则会进入 prompt）。"""
    stripped = (text or "").strip()
    if not stripped:
        raise RuleValidationError("empty_content", "规则内容不能为空")
    if len(stripped) > MAX_RULE_CHARS:
        raise RuleValidationError(
            "content_too_long",
            f"单条规则不能超过 {MAX_RULE_CHARS} 字符",
        )
    scan = get_scanner().scan(stripped, level="all")
    if scan.blocked:
        raise RuleValidationError(
            "unsafe_content",
            f"规则未通过安全扫描：{scan.reason}",
        )
    return stripped


def _section_bounds(content: str, index: int) -> Tuple[int, int]:
    sections = split_markdown_sections(content)
    if index < 0 or index >= len(sections):
        raise RuleValidationError(
            "section_not_found", "规则小节已变化，请刷新后重试", 409
        )
    start = sections[index].start
    end = (
        sections[index + 1].start
        if index + 1 < len(sections)
        else len(content)
    )
    return start, end


def replace_section(content: str, index: int, new_section: str) -> str:
    """替换指定小节；中间小节保留与后续小节之间的空行分隔符。"""
    sections = split_markdown_sections(content)
    if index < 0 or index >= len(sections):
        raise RuleValidationError(
            "section_not_found", "规则小节已变化，请刷新后重试", 409
        )
    start = sections[index].start
    end = (
        sections[index + 1].start
        if index + 1 < len(sections)
        else len(content)
    )
    text = new_section.rstrip("\n")
    tail = "\n\n" if index + 1 < len(sections) else "\n"
    return content[:start] + text + tail + content[end:]


def remove_section(content: str, index: int) -> str:
    start, end = _section_bounds(content, index)
    return content[:start] + content[end:]


def append_section(content: str, heading: str, body: str) -> str:
    title = (heading or "").strip() or "规则"
    block = f"## {title}\n\n{(body or '').strip()}\n"
    if not content.strip():
        return block
    return content.rstrip("\n") + "\n\n" + block


def read_existing_text(path: Path) -> str:
    """缺文件视为空内容；符号链接一律拒绝（防越界写）。"""
    if path.is_symlink():
        raise RuleValidationError("symlink_target", "目标文件是符号链接，拒绝读写")
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def write_text_atomic(path: Path, content: str) -> None:
    """同目录临时文件 + ``os.replace``；父目录尽力收紧到 0700。"""
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise RuleValidationError(
            "content_too_large",
            f"规则文件超过 {MAX_FILE_BYTES} 字节上限",
            413,
        )
    if path.is_symlink():
        raise RuleValidationError("symlink_target", "目标文件是符号链接，拒绝写入")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        parent.chmod(0o700)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        Path(tmp_name).replace(path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
