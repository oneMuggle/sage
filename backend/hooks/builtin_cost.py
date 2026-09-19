"""内置成本预警钩子 (Phase 1)。

stop 事件观察型钩子: 会话结束时检查累计 token 消耗, 超阈值则返回
带 reason 的 allow (调用方据此弹通知)。永不阻断。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 100000


async def cost_alert(
    payload: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """检查会话 token 消耗是否超阈值。

    payload 需包含 (由调用方注入):
        total_tokens: int — 本次会话累计 token
        input_tokens / output_tokens: int — 可选细分

    config keys:
        threshold_tokens: int — 告警阈值 (默认 100000)
    """
    try:
        threshold = config.get("threshold_tokens", _DEFAULT_THRESHOLD)
        if not isinstance(threshold, (int, float)) or threshold <= 0:  # noqa: UP038 — py3.8 兼容
            threshold = _DEFAULT_THRESHOLD

        total = payload.get("total_tokens")
        if not isinstance(total, (int, float)):  # noqa: UP038 — py3.8 兼容
            # payload 未提供 token 统计 → 静默放行
            return {"decision": "allow"}

        if total >= threshold:
            return {
                "decision": "allow",
                "reason": f"成本预警: 本次会话已消耗 {int(total):,} tokens (阈值 {int(threshold):,})",
            }

        return {"decision": "allow"}

    except Exception as exc:
        logger.warning("hooks: cost_alert failed (fail-open): %s", exc)
        return {"decision": "allow", "reason": f"cost_alert error: {exc}"}
