"""注入上下文统一预算 (backend/chat/context_budget.py)。

此前各注入块各管各的：项目资料按字符上限裁剪、记忆固定取 10 条、技能清单
按条数省略……总量不受控。小窗口模型上，注入块会挤占历史，甚至让单轮请求
直接超窗。

这里把头部 system 与尾部动态块（dynamic_context_parts）视为一个整体预算：

- 预算 = 有效窗口 × ``BUDGET_RATIO``（下限 ``MIN_BUDGET_TOKENS``）。窗口未知时不处理。
- **只在超预算时生效**：按 ``TRIM_ORDER`` 从低优先级开始，对块做尾部截断，
  并附上截断说明，而不是整块丢弃。每块至少保留 ``KEEP_TOKENS``（标题 + 开头）。
- 基础系统提示词、环境信息、用户显式添加的附件**永不截断**。
- 块识别复用 ``context_sources`` 的标记切分（与 ContextMeter 来源明细同口径），
  截断后的效果会直接反映在来源明细里。
- 任何异常原样返回输入，绝不阻断聊天。

UX-IA Round 2 · 批次 B（2026-09-30）。保持 Python 3.8 兼容（win7 LTS）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.chat.context_sources import SOURCE_MARKERS, _find_blocks
from backend.memory.working import estimate_tokens

logger = logging.getLogger(__name__)

#: 注入上下文占有效窗口的比例上限
BUDGET_RATIO = 0.35
#: 预算下限（小窗口模型也至少给注入块留这么多）
MIN_BUDGET_TOKENS = 3000
#: 截断时每块至少保留的 token（标题 + 开头部分）
KEEP_TOKENS = 200
#: 截断目标的安全余量：截断说明本身占 token，且分段估算与整体估算有取整误差
_MARGIN_TOKENS = 32
#: 截断顺序：越靠前越先被截（优先级越低）。未列出的来源永不截断。
TRIM_ORDER: Tuple[str, ...] = (
    "project_materials",
    "memory",
    "skills",
    "project_overview",
    "project_constraints",
    "sage_md",
)

_CLOSE_BY_KEY: Dict[str, Optional[str]] = {key: close for key, _, close in SOURCE_MARKERS}


def budget_for_window(window: Optional[int]) -> Optional[int]:
    if not window or window <= 0:
        return None
    return max(MIN_BUDGET_TOKENS, int(window * BUDGET_RATIO))


def _truncate_block(block: str, key: str, target_tokens: int) -> Tuple[str, int]:
    """把块截到约 target_tokens，返回 (新文本, 实际减少的 token)。"""
    before = estimate_tokens(block)
    if before <= target_tokens:
        return block, 0
    close = _CLOSE_BY_KEY.get(key)
    body = block
    if close and body.rstrip().endswith(close):
        body = body.rstrip()[: -len(close)]
    lo, hi = 0, len(body)
    while lo < hi:  # 最长前缀使 estimate_tokens(prefix) <= target
        mid = (lo + hi + 1) // 2
        if estimate_tokens(body[:mid]) <= target_tokens:
            lo = mid
        else:
            hi = mid - 1
    cut = body[:lo].rstrip()
    dropped = before - estimate_tokens(cut)
    note = "\n…[已按上下文预算截断约 {} tokens]".format(max(0, dropped))
    new_block = cut + note + ("\n" + close if close and close in block else "")
    return new_block, max(0, before - estimate_tokens(new_block))


def apply_context_budget(
    system_content: str,
    dynamic_parts: List[str],
    window: Optional[int],
) -> Tuple[str, List[str], Optional[Dict[str, Any]]]:
    """超预算时按优先级截断注入块。

    返回 (新 system_content, 新 dynamic_parts, report)。未超预算或不处理时
    report 为 None；超预算时 report = {budget, before, after, trimmed: {key: tokens}}。
    """
    try:
        budget = budget_for_window(window)
        if budget is None:
            return system_content, dynamic_parts, None
        texts: List[str] = [system_content or ""] + [str(p or "") for p in dynamic_parts]
        before = sum(estimate_tokens(t) for t in texts)
        over = before - budget
        if over <= 0:
            return system_content, dynamic_parts, None

        # 收集可截断块: (优先级, 文本序号, start, end, key)
        candidates: List[Tuple[int, int, int, int, str]] = []
        for ti, text in enumerate(texts):
            for start, end, key in _find_blocks(text):
                if key in TRIM_ORDER:
                    candidates.append((TRIM_ORDER.index(key), ti, start, end, key))
        candidates.sort(key=lambda c: (c[0], c[1], c[2]))

        replacements: Dict[int, List[Tuple[int, int, str]]] = {}
        trimmed: Dict[str, int] = {}
        for _, ti, start, end, key in candidates:
            if over <= 0:
                break
            block = texts[ti][start:end]
            tokens = estimate_tokens(block)
            target = max(KEEP_TOKENS, tokens - over - _MARGIN_TOKENS)
            new_block, saved = _truncate_block(block, key, target)
            if saved <= 0:
                continue
            replacements.setdefault(ti, []).append((start, end, new_block))
            trimmed[key] = trimmed.get(key, 0) + saved
            over -= saved

        if not trimmed:
            return system_content, dynamic_parts, None
        for ti, reps in replacements.items():
            text = texts[ti]
            for start, end, new_block in sorted(reps, key=lambda r: r[0], reverse=True):
                text = text[:start] + new_block + text[end:]
            texts[ti] = text
        after = sum(estimate_tokens(t) for t in texts)
        report = {"budget": budget, "before": before, "after": after, "trimmed": trimmed}
        logger.info("context budget applied: %s", report)
        return texts[0], texts[1:], report
    except Exception as err:  # noqa: BLE001 — 预算是增强逻辑，失败原样放行
        logger.warning("context budget skipped: %s", err)
        return system_content, dynamic_parts, None


__all__ = [
    "BUDGET_RATIO",
    "KEEP_TOKENS",
    "MIN_BUDGET_TOKENS",
    "TRIM_ORDER",
    "apply_context_budget",
    "budget_for_window",
]
