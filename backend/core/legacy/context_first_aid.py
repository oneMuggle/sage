"""上下文急救压缩（RT2，round7 运行时韧性）。

run_loop 迭代之间历史只增不减，唯一防膨胀是工具结果字符帽——当请求仍
超出模型上下文窗口（LLM 返回 400/413 overflow）时，此前唯一出路是整个
run 直接 FAILED。本模块提供**就地机械压缩**作为急救手段：

- ``estimate_messages_tokens``：与 ``backend.memory.working.estimate_tokens``
  同口径的启发式估算（中文按字符、其余按 4 字符 ≈ 1 token）。内联实现，
  避免 core 层依赖 memory 层。
- ``first_aid_compact``：就地截断早期消息内容，**绝不增删消息**——保持
  assistant(tool_calls) ↔ tool 配对完整，压缩后的列表仍能通过任何
  OpenAI 兼容 API 的消息结构校验。
- ``run_ctx_budget_tokens``：迭代边界高水位预算（事前预防），env
  ``SAGE_RUN_CTX_BUDGET_TOKENS`` 可覆盖（0 = 关闭预防性压缩）。

与 LLM 摘要压缩（``backend.chat.compaction``，run 前对持久化历史执行）
的分工：本模块只服务 run_loop 内存列表的确定性急救——不调 LLM、不落盘、
失败面为零；信息损失通过截断标记对模型透明。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

#: 默认 run 级上下文高水位预算（估算 token）。取值高于工具结果 run 预算
#: （256k 字符 ≈ 最坏 6.4 万 token）留出余量，只在真正逼近窗口时触发。
DEFAULT_RUN_CTX_BUDGET_TOKENS = 100_000

#: env 覆盖键（0 = 关闭预防性压缩；爆后修复不受此开关影响）
ENV_RUN_CTX_BUDGET = "SAGE_RUN_CTX_BUDGET_TOKENS"

#: 急救压缩时保持原样的最近消息条数（当前迭代正在对话的"活跃区"）
DEFAULT_KEEP_RECENT = 6

#: 早期 tool 消息保留的头部长度（工具结果对后续迭代的价值随距离衰减）
_TOOL_CAP_CHARS = 400

#: 早期 assistant/user 长内容的截断参数（>800 字符才截）
_PROSE_THRESHOLD_CHARS = 800
_PROSE_HEAD_CHARS = 400
_PROSE_TAIL_CHARS = 100

_TOOL_TRUNCATION_MARK = "\n[已压缩：早期工具结果]"
_PROSE_TRUNCATION_MARK = "\n[已压缩：早期内容]"


def _estimate_text_tokens(text: str) -> int:
    """单段文本 token 估算：中文按字符、其余按 4 字符 ≈ 1 token。

    与 ``backend.memory.working.estimate_tokens`` 逐字同公式（内联实现，
    避免 core → memory 跨层依赖）。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + other // 4 + len(text) // 4


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """估算发给 LLM 的消息列表总 token（role + content）。"""
    total = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        total += _estimate_text_tokens(str(msg.get("role") or ""))
        total += _estimate_text_tokens(str(msg.get("content") or ""))
    return total


def run_ctx_budget_tokens() -> int:
    """读取 run 级高水位预算（env 覆盖 > 默认）。0 表示关闭预防性压缩。"""
    raw = os.environ.get(ENV_RUN_CTX_BUDGET, "").strip()
    if raw:
        try:
            value = int(raw)
            if value >= 0:
                return value
        except ValueError:
            logger.warning("env %s=%r 不是合法整数，回退默认预算", ENV_RUN_CTX_BUDGET, raw)
    return DEFAULT_RUN_CTX_BUDGET_TOKENS


def _truncate_prose(content: str) -> str:
    """截断早期 assistant/user 长内容：保头尾 + 标记。"""
    return (
        content[:_PROSE_HEAD_CHARS]
        + _PROSE_TRUNCATION_MARK
        + (content[-_PROSE_TAIL_CHARS:] if _PROSE_TAIL_CHARS else "")
    )


def _compact_entry(msg: Dict[str, Any]) -> bool:
    """就地压缩单条消息；返回是否发生了截断。"""
    role = str(msg.get("role") or "")
    content = str(msg.get("content") or "")
    if not content:
        return False
    if role == "tool":
        if len(content) <= _TOOL_CAP_CHARS:
            return False
        msg["content"] = content[:_TOOL_CAP_CHARS] + _TOOL_TRUNCATION_MARK
        return True
    if role in ("assistant", "user"):
        if len(content) <= _PROSE_THRESHOLD_CHARS:
            return False
        msg["content"] = _truncate_prose(content)
        return True
    return False


def first_aid_compact(
    messages: List[Dict[str, Any]],
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> Tuple[int, int]:
    """就地机械压缩消息列表，返回 (估算 token 压缩前, 压缩后)。

    规则（确定性，无 LLM 参与）：
    - 消息条数不变、顺序不变、role 不变——assistant(tool_calls) ↔ tool
      配对完整保留，tool_call_id 原样；
    - 末尾 ``keep_recent`` 条原样保留（活跃对话区）；
    - 更早的消息：tool 内容截到头 ``_TOOL_CAP_CHARS`` 字符 + 标记；
      assistant/user 超长内容保头尾 + 标记；
    - 其他角色（system 等）不动。

    绝不抛错：单条消息处理失败（非法结构等）跳过该条继续。
    """
    if not messages:
        return (0, 0)
    before = estimate_messages_tokens(messages)
    protected_start = max(0, len(messages) - max(0, keep_recent))
    truncated_count = 0
    for index, msg in enumerate(messages):
        if index >= protected_start:
            continue
        if not isinstance(msg, dict):
            continue
        try:
            if _compact_entry(msg):
                truncated_count += 1
        except Exception as exc:  # noqa: BLE001 — 急救路径绝不因单条消息失败
            logger.debug("急救压缩跳过第 %d 条消息: %s", index, exc)
    after = estimate_messages_tokens(messages)
    if truncated_count:
        logger.info(
            "上下文急救压缩：截断 %d 条早期消息，估算 token %d → %d",
            truncated_count,
            before,
            after,
        )
    return (before, after)
