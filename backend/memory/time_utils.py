"""记忆/会话时间戳工具（毫秒单一真相源）。

背景（2026-11-17）：``memories_episodic`` / ``memories_semantic`` /
``sessions`` 仓储层写入的是毫秒时间戳（``int(time.time() * 1000)``），
但部分进化任务的 SQL 阈值按秒比较，导致修剪/衰减/每日摘要永不命中。
本模块提供唯一的毫秒获取与归一入口，避免各模块再各自判断单位。

约定：

* 记忆表 / 会话表 / ``memories_evolution_log``：毫秒；
* ``evolution_log.created_at``：秒（前端按 ``created_at * 1000`` 渲染的
  既有契约，保持不变）。
"""

# ruff: noqa: UP045 — release/win7 需保持 Python 3.8 可解析的类型注解

from __future__ import annotations

import time
from typing import Any, Optional

#: 小于该值的时间戳按「秒」解释（约 5138 年，远大于当前 epoch 秒值）
SECOND_LIKE_LIMIT = 100_000_000_000


def now_ms() -> int:
    """当前 epoch 毫秒。"""
    return int(time.time() * 1000)


def to_ms(value: Optional[Any], assume: str = "auto") -> Optional[int]:
    """把时间戳归一到毫秒。

    Args:
        value: 秒/毫秒时间戳，或可转 int/float 的字符串。
        assume: ``auto``（默认，< SECOND_LIKE_LIMIT 视为秒）、
            ``s``（强制按秒）、``ms``（强制按毫秒）。

    Returns:
        毫秒整数；``None``、非法值或非正数返回 ``None``。
    """
    if value is None:
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if assume == "s":
        return int(raw * 1000)
    if assume == "ms":
        return int(raw)
    return int(raw * 1000) if raw < SECOND_LIKE_LIMIT else int(raw)


def seconds_to_ms(value: Optional[Any]) -> Optional[int]:
    """强制把秒级时间戳转成毫秒（别名，便于调用点自解释）。"""
    return to_ms(value, assume="s")


__all__ = ["SECOND_LIKE_LIMIT", "now_ms", "seconds_to_ms", "to_ms"]
