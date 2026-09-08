"""session_extractor — 校验/标准化 LLM 传入的工具调用序列。

skill_save 工具要求 LLM 在调用时显式传入 ``tool_sequence``(刚执行的工具步骤)。
LLM 可能:
- 漏字段(没 ``tool`` 或没 ``args``)
- 类型错(``tool`` 不是字符串 / ``args`` 不是 dict)
- 数量过大(超过 20 上限)

本模块把这些"脏输入"标准化成 ``SkillSaveTool`` 能安全消费的形态:
- 过滤掉非 dict / 缺字段 / 类型错的记录
- 裁剪到 ``MAX_SEQUENCE_LEN`` 上限(保留最后 N 条,丢弃最旧的)
- 不修改输入(返回新列表)

不读 / 不写 data file;纯函数 + 常量。
"""

from __future__ import annotations

from typing import Any, Dict, List

MAX_SEQUENCE_LEN = 20
REQUIRED_FIELDS = ("tool", "args")


def normalize_tool_sequence(
    raw_sequence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """校验并裁剪 LLM 传入的工具调用序列。

    过滤规则(全部满足才保留):
    - record 必须是 ``dict``
    - ``tool`` 字段存在且为 ``str``
    - ``args`` 字段存在且为 ``dict``

    裁剪规则:
    - 保留最后 ``MAX_SEQUENCE_LEN`` 条记录,丢弃最旧的

    Args:
        raw_sequence: LLM 传入的工具调用序列(可能脏)。

    Returns:
        新的 list(不修改输入);空 list 当输入为空或全部记录不合规。
    """
    cleaned: List[Dict[str, Any]] = []
    for record in raw_sequence:
        if not isinstance(record, dict):
            continue
        tool_name = record.get("tool")
        args = record.get("args")
        if not isinstance(tool_name, str):
            continue
        if not isinstance(args, dict):
            continue
        cleaned.append(record)
    if len(cleaned) > MAX_SEQUENCE_LEN:
        cleaned = cleaned[-MAX_SEQUENCE_LEN:]
    return cleaned


__all__ = ["MAX_SEQUENCE_LEN", "REQUIRED_FIELDS", "normalize_tool_sequence"]
