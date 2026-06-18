"""SKILL.md frontmatter 解析器。

解析 ``---\\n<yaml>\\n---\\n<body>`` 形式的 markdown 文件。

设计要点
--------

- 手写 fence 切分(避免依赖 python-frontmatter),逻辑与
  ``archive/src-tauri-2026-06-13-main-migration/src/wiki/frontmatter.rs``
  思路一致但更宽松: 只识别深度 1 的 opening/closing fence, body 内的
  ``---`` 子串**不**当成 fence (用例 ``test_parse_preserves_unclosed_fence_in_body``)。
- YAML 解析走现成 ``yaml.safe_load`` (``backend/main.py:41-48`` 同款用法),
  ``pyyaml==6.0.1`` 已在 ``backend/requirements.txt:23``。
- 解析失败包装为 ``SkillMdParseError(ValueError)``, 携带原始 ``yaml.YAMLError``
  作为 ``__cause__``(PEP 3134)。
- 校验只强制 ``name`` (合法 slug) + ``description`` (非空字符串) 两项必填。
  其他字段(``version`` / ``platforms`` / ``triggers`` / ``metadata`` ...)原样保留,
  未知字段不报错(为 AgentSkills 规范演化预留空间)。
- 入口处理 UTF-8 BOM (``\\ufeff``), 兼容 Windows 工具保存的 markdown 文件。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_FENCE = "---"
_NAME_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_BOM = "﻿"


class SkillMdParseError(ValueError):
    """SKILL.md 解析失败。"""


def _strip_bom(text: str) -> str:
    """剥除 UTF-8 BOM(若存在)。"""
    if text.startswith(_BOM):
        return text[1:]
    return text


def _split_frontmatter(text: str) -> tuple[str, str]:
    """切分 frontmatter 与 body。

    Returns:
        (frontmatter_yaml_text, body_text)。
        若没有 opening fence, frontmatter_yaml_text 为空字符串, body_text = 原 text。

    Raises:
        SkillMdParseError: 有 opening fence 但找不到 closing fence。
    """
    # 先判断是否以 fence 开头
    if not text.startswith(_FENCE):
        return "", text

    # opening fence 之后必须紧跟换行(LF 或 CRLF), 否则不算合法开头
    after_open = text[len(_FENCE) :]
    if not after_open or after_open[0] not in ("\n", "\r"):
        return "", text

    # 找 closing fence 行: 一行内容恰好是 "---" (可带尾随空白)
    lines = after_open.splitlines(keepends=True)

    for i, line in enumerate(lines):
        # 去掉行尾的 \n/\r\n, 判断内容是否就是 ---
        stripped = line.rstrip("\r\n")
        if stripped == _FENCE:
            # closing fence 找到了
            frontmatter_lines = lines[:i]
            body_lines = lines[i + 1 :]
            frontmatter_text = "".join(frontmatter_lines)
            body_text = "".join(body_lines)
            # markdown 习惯: closing fence 之后紧跟的空行仅作分隔, 不属于 body
            body_text = body_text.lstrip("\r\n")
            return frontmatter_text, body_text

    # 走完所有行都没找到 closing fence → 错误
    raise SkillMdParseError("unclosed frontmatter fence: missing closing '---'")


def _validate_name(name: Any) -> str:
    """校验 name 是合法 slug(小写字母/数字/连字符)。"""
    if not isinstance(name, str) or not name:
        raise SkillMdParseError("frontmatter 'name' must be a non-empty string")
    if not _NAME_SLUG_RE.match(name):
        raise SkillMdParseError(
            f"frontmatter 'name' must be a slug (lowercase letters/digits/hyphens), got: {name!r}"
        )
    return name


def _validate_description(description: Any) -> str:
    if not isinstance(description, str) or not description:
        raise SkillMdParseError("frontmatter 'description' must be a non-empty string")
    return description


def _validate_requires(requires: Any) -> dict[str, Any]:
    """校验 requires 字段（v2）。"""
    if requires is None:
        return {}
    if not isinstance(requires, dict):
        raise SkillMdParseError(f"frontmatter 'requires' must be a dict, got {type(requires).__name__}")
    # 校验子字段
    for key in ("bins", "env", "config"):
        if key in requires:
            val = requires[key]
            if not isinstance(val, list):
                raise SkillMdParseError(f"frontmatter 'requires.{key}' must be a list")
            if not all(isinstance(item, str) for item in val):
                raise SkillMdParseError(f"frontmatter 'requires.{key}' must be a list of strings")
    return requires


def _validate_os(os_field: Any) -> list[str]:
    """校验 os 字段（v2）。"""
    if os_field is None:
        return []
    if not isinstance(os_field, list):
        raise SkillMdParseError(f"frontmatter 'os' must be a list, got {type(os_field).__name__}")
    valid_platforms = {"macos", "linux", "windows"}
    for platform in os_field:
        if not isinstance(platform, str):
            raise SkillMdParseError(f"frontmatter 'os' must be a list of strings")
        if platform not in valid_platforms:
            raise SkillMdParseError(
                f"frontmatter 'os' contains invalid platform '{platform}', "
                f"valid platforms are: {', '.join(sorted(valid_platforms))}"
            )
    return os_field


def _validate_always(always: Any) -> bool:
    """校验 always 字段（v2）。"""
    if always is None:
        return False
    if not isinstance(always, bool):
        raise SkillMdParseError(f"frontmatter 'always' must be a bool, got {type(always).__name__}")
    return always


def _validate_command_dispatch(command_dispatch: Any) -> str:
    """校验 command-dispatch 字段（v2）。"""
    if command_dispatch is None:
        return "auto"
    valid_modes = {"auto", "tool", "prompt"}
    if not isinstance(command_dispatch, str):
        raise SkillMdParseError(
            f"frontmatter 'command-dispatch' must be a string, got {type(command_dispatch).__name__}"
        )
    if command_dispatch not in valid_modes:
        raise SkillMdParseError(
            f"frontmatter 'command-dispatch' must be one of {', '.join(sorted(valid_modes))}, "
            f"got '{command_dispatch}'"
        )
    return command_dispatch


def parse(text: str) -> tuple[dict[str, Any], str]:
    """解析 SKILL.md 文本, 返回 (frontmatter_dict, body)。

    - 无 frontmatter → 返回 ``({}, text)``。
    - 有 frontmatter 但缺 ``name``/``description`` 或 ``name`` 不合法 → 抛 ``SkillMdParseError``。
    - YAML 语法错 → 抛 ``SkillMdParseError``(``__cause__`` 是 ``yaml.YAMLError``)。
    """
    text = _strip_bom(text)

    # 没有 opening fence 的快速路径
    if not text.startswith(_FENCE):
        return {}, text

    fm_text, body = _split_frontmatter(text)

    if fm_text == "":
        # 有 opening fence 但 frontmatter 内容为空 ("---\n---\n...")
        # 这种情况也算"无 frontmatter", 整个作为 body
        # 但要确认没有 closing fence 引发异常, _split_frontmatter 已经处理了
        return {}, body

    try:
        meta = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise SkillMdParseError(f"invalid YAML in frontmatter: {exc}") from exc

    if meta is None:
        # 全注释或空 YAML
        meta = {}
    if not isinstance(meta, dict):
        raise SkillMdParseError(f"frontmatter must be a YAML mapping, got {type(meta).__name__}")

    _validate_name(meta.get("name"))
    _validate_description(meta.get("description"))

    # v2 字段校验
    _validate_requires(meta.get("requires"))
    _validate_os(meta.get("os"))
    _validate_always(meta.get("always"))
    _validate_command_dispatch(meta.get("command-dispatch"))

    return meta, body


def parse_file(path: Path) -> tuple[dict[str, Any], str]:
    """读盘并解析 SKILL.md。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SkillMdParseError(f"SKILL.md not found: {path}") from exc
    except OSError as exc:
        raise SkillMdParseError(f"failed to read SKILL.md {path}: {exc}") from exc
    return parse(text)


def dump(meta: dict[str, Any], body: str) -> str:
    """序列化 frontmatter dict + body 为 SKILL.md 文本(测试用 round-trip)。"""
    dumped = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    # safe_dump 默认末尾加 '\n...', 我们要 "---...\n---\n" 的形态
    return f"{_FENCE}\n{dumped}{_FENCE}\n{body}"
