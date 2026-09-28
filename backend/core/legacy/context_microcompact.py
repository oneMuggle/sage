"""上下文微压缩（microcompact）—— run_loop 迭代边界的廉价压缩层。

``run_loop`` 迭代之间历史只增不减，而工具结果往往是其中最占地的部分：
一次 ``read_file`` 可返回大段文件内容，``web_fetch`` 可返回整页 HTML，且这些
结果在后续每一轮迭代都会被重复发送。与 :func:`context_first_aid.first_aid_compact`
的分工——

- 本模块**只处理白名单工具的旧结果**，动作是清空内容换成哨兵串（省得最多、
  最便宜、无 LLM 调用），代价是这部分信息不可恢复；
- ``first_aid_compact`` 覆盖全部早期消息，动作是保头尾截断（保 400 字符），
  可恢复的信息多于本模块但省得少。

两者串联使用：先 micro（省得多就停），不够再 first_aid。

**本期未接第三级**：计划里排的 ``ContextCompactor`` LLM 摘要层没有接进
``run_loop`` 的预防路径。理由是它会给每次迭代边界增加一次 LLM 往返（成本
远高于前两级），且位于 ``application/services``——从 ``core/legacy`` 向上
依赖是六边形重构正在消除的方向，不该新增这种调用点。超预算的兜底仍由既有的
溢出急救环（``_MAX_FIRST_AID_ATTEMPTS``）承担。

**结构不变量**：本模块**绝不增删消息**。被清空的条目保持 ``role="tool"``、
``tool_call_id`` 原样，仅 ``content`` 变为哨兵串——assistant(tool_calls) ↔
tool 的配对因此不断裂，与 ``first_aid_compact`` docstring 承诺的不变量一致。

对标 ZCode ``core/src/compact/microcompact.ts``（KEEP_RECENT_TOOL_RESULTS /
MIN_TOKEN_SAVINGS / 哨兵串三个机制）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set, Tuple

from backend.core.legacy.context_first_aid import _estimate_text_tokens, estimate_messages_tokens

logger = logging.getLogger(__name__)

#: 可被清空旧结果的工具白名单。筛选标准：该工具的输出可以被重新获取——
#: 重新读文件、重跑命令、再抓一次网页。工具名取自 ``backend.domain.tool_names``
#: （内置工具名单一来源，历史上出现过 terminal→bash、file_read→read_file 的漂移）。
MICROCOMPACTABLE_TOOLS = frozenset(
    {
        # 文件读写与目录：结果可重新 read / ls 拿到
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
        # shell：命令输出可重跑复现
        "bash",
        "bash_output",
        # 网络抓取：可重新请求
        "web_search",
        "web_fetch",
        "http_download",
    }
)

#: 保留原样的最近 N 条工具结果——当前迭代正在依赖它们，清掉等于让模型
#: 立刻失明重查。
KEEP_RECENT_TOOL_RESULTS = 5

#: 预计节省不足此 token 数则不动手。改写历史本身有成本（重写消息列表、
#: 丢弃已算好的估算），省两三个 token 不值当，还会引发逐轮抖动。
MIN_TOKEN_SAVINGS = 256

#: 清空后的占位内容。必须是非空短串：content 为空串时，部分 OpenAI 兼容
#: 实现会拒绝该条 tool 消息。
CLEARED_SENTINEL = "[旧工具结果已清除]"


def _tool_name_index(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    """建立 ``tool_call_id → 工具名`` 索引。

    run_loop 追加 tool 消息时只写 ``role`` / ``tool_call_id`` / ``content``，
    不带 ``name``，所以工具名要从配对的 assistant.tool_calls 反查。反查
    不到时保守跳过——宁可不压缩，也不误清白名单外的结果。
    """
    index: Dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for call in msg.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            call_id = call.get("id")
            function = call.get("function")
            name = function.get("name") if isinstance(function, dict) else None
            if isinstance(call_id, str) and isinstance(name, str):
                index[call_id] = name
    return index


def _tool_name_of(msg: Dict[str, Any], name_index: Dict[str, str]) -> str:
    """取 tool 消息记录的工具名：先看自带 ``name``，否则按 id 反查。"""
    name = msg.get("name")
    if isinstance(name, str) and name:
        return name
    call_id = msg.get("tool_call_id")
    return name_index.get(call_id, "") if isinstance(call_id, str) else ""


def _clearable_indexes(messages: List[Dict[str, Any]]) -> List[int]:
    """可清空的 tool 消息下标（已排除最近 N 条与已清空的）。"""
    name_index = _tool_name_index(messages)
    candidates = [
        index
        for index, msg in enumerate(messages)
        if isinstance(msg, dict)
        and msg.get("role") == "tool"
        and _tool_name_of(msg, name_index) in MICROCOMPACTABLE_TOOLS
        and msg.get("content") != CLEARED_SENTINEL
    ]
    protected: Set[int] = set(candidates[-KEEP_RECENT_TOOL_RESULTS:]) if candidates else set()
    return [index for index in candidates if index not in protected]


def _total_estimate(messages: List[Dict[str, Any]]) -> int:
    """消息列表的总 token 估算（复用 first_aid 的口径，保证两层可比）。"""
    return estimate_messages_tokens(messages)


def estimate_savings(messages: List[Dict[str, Any]]) -> int:
    """估算清空白名单旧结果能省下的 token 数（不做任何改动）。

    供调用方在真正动手前预判收益，避免无谓的历史改写。
    """
    sentinel_cost = _estimate_text_tokens(CLEARED_SENTINEL)
    saved = 0
    for index in _clearable_indexes(messages):
        content = str(messages[index].get("content") or "")
        saved += _estimate_text_tokens(content) - sentinel_cost
    return max(0, saved)


def micro_compact(
    messages: List[Dict[str, Any]],
    min_token_savings: int = MIN_TOKEN_SAVINGS,
) -> Tuple[int, int]:
    """就地清空白名单工具的旧结果，返回 (压缩前 token 估算, 压缩后估算)。

    行为约定：

    - 只动 ``role="tool"`` 且工具名在白名单内的条目；
    - 保留最近 ``KEEP_RECENT_TOOL_RESULTS`` 条工具结果原样；
    - 预计节省不足 ``min_token_savings`` 时**不动手**，两个返回值都等于
      当前总量——调用方据此可判断"这轮没省到东西"并降级到下一层；
    - 绝不增删消息，``tool_call_id`` 与条目顺序原样保留。

    绝不抛错：单条消息写入失败（非法结构等）跳过该条继续——它跑在
    run_loop 的迭代边界，失败不应中断整轮对话。
    """
    if not messages:
        return (0, 0)

    clearable = _clearable_indexes(messages)
    if not clearable:
        total = _total_estimate(messages)
        return (total, total)

    before = _total_estimate(messages)
    savings = estimate_savings(messages)
    if savings < min_token_savings:
        logger.debug(
            "microcompact 跳过：预计节省 %d token < 阈值 %d（%d 条可清空）",
            savings,
            min_token_savings,
            len(clearable),
        )
        return (before, before)

    cleared = 0
    for index in clearable:
        try:
            messages[index]["content"] = CLEARED_SENTINEL
            cleared += 1
        except Exception as exc:  # noqa: BLE001 — 压缩路径绝不因单条消息失败
            logger.debug("microcompact 跳过第 %d 条消息: %s", index, exc)

    if cleared:
        logger.info("microcompact 清空 %d 条旧工具结果，预计节省 %d token", cleared, savings)

    # 少数条目写入失败时 before - savings 不再等于实际值，重测更稳。
    return (before, _total_estimate(messages))
