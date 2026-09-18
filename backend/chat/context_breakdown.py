"""上下文分类明细估算 + provider 实报校准 (backend/chat/context_breakdown.py)。

ContextMeter 此前只显示 `上一轮 prompt_tokens / 窗口` 一个总数——provider
不返回 prompt 构成拆分,明细只能在**请求装配完成后、发送前**对最终
payload（messages + tools）按类别估算,响应回来后按实报 ``prompt_tokens``
比例校准（各块估算和缩放到实报总数,最大余数法保证逐类相加恰等于总数）。

类别口径（按转换后的请求消息体识别,天然覆盖 run_loop 每次迭代的实时构成,
含工具往返）:

- ``tools``            工具 schema 定义（OpenAI function 格式整包序列化）
- ``system``           头部 system 消息（扣除技能清单块）
- ``skills``           头部 system 内的 ``<available-skills>`` 块
- ``dynamic_context``  非头部的 system 消息（环境/记忆/附件/项目上下文等
                       经 trailing_system / attachment_block 注入的易变块）
- ``history_user``     历史 user 消息（最后一条 user 之前的全部）
- ``history_assistant``历史 assistant 消息（含 tool_calls 参数——旧估算器
                       漏算的部分）
- ``history_tool``     tool 角色消息（工具结果）
- ``current_input``    最后一条 user 消息（本轮输入;agent 循环后续迭代
                       中它仍是"本轮"的锚点）

估算口径复用 ``backend.memory.working.estimate_tokens``（中文按字符、其余
4 字符≈1 token）,与压缩/截断同一口径;多模态图片部分按固定常数计。校准
后 ``categories`` 之和恰等于 provider 实报 prompt_tokens,残差体现在各类
放大系数上而非独立桶。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.memory.working import estimate_tokens

#: 技能清单块标记（与 backend.chat.env_context.build_skills_block 对齐）
_SKILLS_OPEN = "<available-skills>"
_SKILLS_CLOSE = "</available-skills>"

#: 每条消息的角色/分隔符等结构开销（启发式常数,校准吸收误差）
_MSG_OVERHEAD_TOKENS = 4

#: 单张多模态图片的估算 token（各系模型 765~1600 之间,取中位粗估）
_IMAGE_PART_TOKENS = 1000

#: 明细类别的展示顺序（前端堆叠条按此序渲染）
CATEGORY_ORDER = (
    "tools",
    "system",
    "skills",
    "dynamic_context",
    "current_input",
    "history_tool",
    "history_assistant",
    "history_user",
)


def _content_tokens(content: Any) -> int:
    """消息 content 的估算 token——str 或 OpenAI 多模态 parts 列表。"""
    if content is None:
        return 0
    if isinstance(content, str):
        return estimate_tokens(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                total += estimate_tokens(str(part.get("text") or ""))
            elif ptype in ("image_url", "image"):
                total += _IMAGE_PART_TOKENS
            else:
                total += estimate_tokens(json.dumps(part, ensure_ascii=False, default=str))
        return total
    return estimate_tokens(str(content))


def _split_skills(system_text: str) -> tuple:
    """从头部 system 文本中拆出技能清单块,返回 (基础部分 token, 技能部分 token)。"""
    start = system_text.find(_SKILLS_OPEN)
    if start < 0:
        return estimate_tokens(system_text), 0
    end = system_text.find(_SKILLS_CLOSE, start)
    end = len(system_text) if end < 0 else end + len(_SKILLS_CLOSE)
    skills_tokens = estimate_tokens(system_text[start:end])
    base_tokens = estimate_tokens(system_text[:start] + system_text[end:])
    return base_tokens, skills_tokens


def _msg_field(msg: Dict[str, Any], key: str) -> Any:
    if isinstance(msg, dict):
        return msg.get(key)
    return getattr(msg, key, None)


def compute_context_breakdown(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    """对最终请求 payload 按类别估算 token 数。

    Args:
        messages: **转换后**（``LLMClient._convert_messages`` 出口）的请求消息
            列表——role/content/tool_calls 形态。
        tools: OpenAI function 格式的工具 schema 列表。

    Returns:
        ``{类别: 估算 token}``,类别键见 ``CATEGORY_ORDER``;无内容的类别为 0。
    """
    buckets: Dict[str, int] = {key: 0 for key in CATEGORY_ORDER}

    # tools:整个 schema 序列化估算（名字+描述+参数定义都要进 prompt）
    if tools:
        buckets["tools"] += estimate_tokens(
            json.dumps(tools, ensure_ascii=False, default=str)
        )

    # 定位最后一条 user 消息 = current_input 锚点
    last_user_index = -1
    for i, msg in enumerate(messages):
        if _msg_field(msg, "role") == "user":
            last_user_index = i

    first_system_seen = False
    for i, msg in enumerate(messages):
        role = _msg_field(msg, "role")
        overhead = _MSG_OVERHEAD_TOKENS
        cost = _content_tokens(_msg_field(msg, "content")) + overhead
        # assistant 的 tool_calls 参数同样占 context（旧口径漏算）
        tool_calls = _msg_field(msg, "tool_calls")
        if tool_calls:
            cost += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False, default=str))

        if role == "system":
            if not first_system_seen:
                first_system_seen = True
                base, skills = _split_skills(str(_msg_field(msg, "content") or ""))
                buckets["system"] += base
                buckets["skills"] += skills
            else:
                buckets["dynamic_context"] += cost
        elif role == "tool":
            buckets["history_tool"] += cost
        elif role == "user":
            if i == last_user_index:
                buckets["current_input"] += cost
            else:
                buckets["history_user"] += cost
        else:  # assistant 及其余角色
            buckets["history_assistant"] += cost

    return buckets


def calibrate_breakdown(
    breakdown: Dict[str, int], actual_prompt_tokens: int
) -> Dict[str, int]:
    """把各类估算按 provider 实报 prompt_tokens 等比校准（最大余数法）。

    估算总和为 0 或实报值非正时原样返回（无从校准）。返回的字典各类之和
    恰等于 ``actual_prompt_tokens``。
    """
    est_total = sum(breakdown.values())
    if est_total <= 0 or actual_prompt_tokens <= 0:
        return dict(breakdown)

    scale = actual_prompt_tokens / est_total
    floored: Dict[str, int] = {}
    remainders: List[tuple] = []
    for key, est in breakdown.items():
        exact = est * scale
        base = int(exact)
        floored[key] = base
        remainders.append((exact - base, est, key))

    allocated = sum(floored.values())
    leftover = actual_prompt_tokens - allocated
    # 余数从大到小补齐;并列时估算值大的类别优先
    for _, _, key in sorted(remainders, key=lambda r: (-r[0], -r[1])):
        if leftover <= 0:
            break
        floored[key] += 1
        leftover -= 1
    return floored


#: 输出侧预留默认值——与 ``LLMConfig.max_tokens`` 默认一致 (4096)。
DEFAULT_OUTPUT_RESERVE_TOKENS = 4096


def measure_request_reserve(
    system_content: str,
    *,
    attachment_block: Optional[str] = None,
    trailing_system: Optional[str] = None,
    user_content: Any = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    output_reserve: int = DEFAULT_OUTPUT_RESERVE_TOKENS,
) -> int:
    """实测本轮请求的**非历史**开销（token）。

    ``history_token_budget`` 的预留位不再是拍脑袋的 16384：system/附件/
    动态上下文/本轮输入/工具 schema 按实际大小估算，另加输出预算
    ``output_reserve``。调用方（legacy producer）在截断历史之前即可算出,
    因为这些部分都不依赖历史。
    """
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_content}]
    if attachment_block:
        messages.append({"role": "system", "content": attachment_block})
    if trailing_system:
        messages.append({"role": "system", "content": trailing_system})
    if user_content:
        messages.append({"role": "user", "content": user_content})
    total = sum(compute_context_breakdown(messages, tools).values())
    return int(total) + max(0, int(output_reserve))


def build_breakdown_snapshot(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    actual_prompt_tokens: Optional[int],
) -> Dict[str, Any]:
    """一步产出可落库的明细快照。

    ``actual_prompt_tokens`` 为 provider 实报值（若有）——传入时各类校准到
    实报总数;为 None/0 时保留原始估算并标记 ``calibrated: false``。
    """
    estimate = compute_context_breakdown(messages, tools)
    est_total = sum(estimate.values())
    categories = estimate
    calibrated = False
    if actual_prompt_tokens and actual_prompt_tokens > 0:
        categories = calibrate_breakdown(estimate, int(actual_prompt_tokens))
        calibrated = True
    return {
        "categories": categories,
        "estimated_total": est_total,
        "prompt_tokens": int(actual_prompt_tokens or 0) or None,
        "calibrated": calibrated,
    }


__all__ = [
    "CATEGORY_ORDER",
    "DEFAULT_OUTPUT_RESERVE_TOKENS",
    "build_breakdown_snapshot",
    "calibrate_breakdown",
    "compute_context_breakdown",
    "measure_request_reserve",
]
