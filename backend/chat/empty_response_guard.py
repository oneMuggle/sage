"""空响应守卫共享件——hex /chat 与 legacy run_loop 共用（双栈收敛切片 B）。

两栈行为对齐：
- 注入同一 system 提示文案后重试；
- 重试上限统一读 ``SAGE_EMPTY_RESPONSE_MAX_RETRIES``（默认 2，<=0 = 关闭守卫）；
- 耗尽终态差异为**显式既有行为**，不在本模块内抹平：
  legacy run_loop → DONE + 兜底文案；hex → 保留原空响应（不 FAILED）。
"""

from __future__ import annotations

import os
from typing import Any, List, Optional

EMPTY_RESPONSE_SYSTEM_PROMPT = (
    "上一次响应内容为空。请直接给出完整回复；若任务无法继续，请说明原因。"
)
EMPTY_RESPONSE_FALLBACK_TEXT = "（模型连续返回空响应，已停止重试。请重试或换个问法。）"
EMPTY_RESPONSE_ENV = "SAGE_EMPTY_RESPONSE_MAX_RETRIES"
DEFAULT_MAX_RETRIES = 2


def empty_response_max_retries() -> int:
    """重试上限：env 覆盖，非法值回退默认 2，<=0 = 关闭守卫（保持旧行为）。"""
    try:
        return int(os.getenv(EMPTY_RESPONSE_ENV, str(DEFAULT_MAX_RETRIES)))
    except ValueError:
        return DEFAULT_MAX_RETRIES


def is_blank_response(tool_calls: Optional[List[Any]], content: Optional[str]) -> bool:
    """既无工具调用又无非空正文 → 空响应。"""
    return not tool_calls and not (content or "").strip()
