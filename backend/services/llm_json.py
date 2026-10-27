"""LLM 输出 JSON 提取共享工具（2026-10-27）。

LLM 返回的「JSON 块」常被包裹在 ```json 围栏、说明文字、多余注释里。
本模块提供两级解析：
1. ``extract_json_object`` 返回首个 JSON 对象字符串
2. ``parse_json`` 解析为 Python dict

调用方（`project_advisor` / `project_analysis_agent` / `project_rule_generator`）
共享同一套解析策略，避免重复实现。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)

#: 匹配 ```json ... ``` 围栏（含 ````python`` 等变体）
_FENCE_PATTERN = re.compile(
    r"```(?:json|json5|jsonc)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE
)


def strip_code_fences(text: str) -> str:
    """移除 ```` ```json ``` ```` 围栏，返回内层文本。

    Args:
        text: 原始文本（可含多个围栏，仅剥离首个）

    Returns:
        剥离后的文本；若无围栏，原样返回
    """
    match = _FENCE_PATTERN.search(text)
    if not match:
        return text
    return match.group(1).strip()


def extract_json_object(text: str) -> str:
    """从文本中定位首个 JSON 对象（首个 ``{`` 到末个 ``}``）。

    适用场景：LLM 在 JSON 前后附带了说明文字（"以下是治理方案："），
    但 JSON 本身完整。

    Args:
        text: 清理后的文本

    Returns:
        JSON 对象字符串

    Raises:
        ValueError: 找不到匹配的括号对
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no balanced JSON object found")
    return text[start : end + 1]


def parse_json(raw: str) -> Dict[str, Any]:
    """从 LLM 输出中提取并解析首个 JSON 对象。

    解析策略（按顺序）：
    1. 直接 ``json.loads``
    2. 剥离 ```` ```json ``` ```` 围栏后再解析
    3. 定位首个 ``{`` 到末个 ``}`` 的区间后解析
    4. 都失败则抛出 ``ValueError``

    Args:
        raw: LLM 原始输出

    Returns:
        解析后的 dict

    Raises:
        ValueError: 无法解析为 JSON 对象
    """
    if not raw or not raw.strip():
        raise ValueError("empty response")

    cleaned = raw.strip()

    # 策略 1：直接解析
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # 策略 2：剥离围栏
    stripped = strip_code_fences(cleaned)
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # 策略 3：括号定位
    try:
        fragment = extract_json_object(stripped)
        obj = json.loads(fragment)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    raise ValueError("could not parse JSON object from LLM response")


__all__ = [
    "extract_json_object",
    "parse_json",
    "strip_code_fences",
]
