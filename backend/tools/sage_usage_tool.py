"""M1.4 ``sage_usage`` 工具 —— 用量与成本自省。

包装 ``backend.services.usage_tracker`` 的 ``summary_with_range()``
（全局 today/7d/30d/total）和 ``session_summary()``（当前会话）。

对应 Claude Code 的 ``/cost`` / ``/usage`` 命令。工具本身 ``RiskClass.READ``。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

_VALID_RANGES = ("today", "7d", "30d", "total")
_VALID_SCOPES = ("global", "session")

# by_model 最多返回多少条，避免工具输出膨胀
_MAX_MODELS = 10


class SageUsageTool(BaseTool):
    """查询 Sage 用量与成本（全局按范围 / 当前会话）。"""

    risk: RiskClass = RiskClass.READ

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="sage_usage",
            description=(
                "查询 Sage 的 LLM 用量与估算成本。scope=global 时按 range"
                "（today/7d/30d/total）返回全局聚合（tokens、请求数、"
                "cache 命中率、按模型分组）；scope=session 时返回当前会话的"
                "累计用量与延迟统计（avg/p95/max latency）。estimated_cost_usd "
                "为 null 表示模型定价未知（不静默按 0 处理）。用于回答"
                "'今天花了多少钱'、'这个会话用了多少 token'、"
                "'哪个模型用得最多'等问题。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": list(_VALID_SCOPES),
                        "description": "global=全局聚合；session=当前会话累计。默认 global。",
                        "default": "global",
                    },
                    "range": {
                        "type": "string",
                        "enum": list(_VALID_RANGES),
                        "description": (
                            "仅 scope=global 时生效。today=本地当日（重启不丢），"
                            "7d/30d=最近 N 天 rollup，total=全量。默认 today。"
                        ),
                        "default": "today",
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "仅 scope=session 时生效；省略则使用当前工具执行"
                            "上下文的会话。"
                        ),
                    },
                },
            },
        )

    def execute(
        self,
        scope: str = "global",
        range: str = "today",  # noqa: A002 —— 与 usage_tracker 公开 API 的命名对齐
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if scope not in _VALID_SCOPES:
            return ToolResult(
                success=False,
                error=f"无效 scope: {scope!r}（可选: {', '.join(_VALID_SCOPES)}）",
            )
        if scope == "global" and range not in _VALID_RANGES:
            return ToolResult(
                success=False,
                error=f"无效 range: {range!r}（可选: {', '.join(_VALID_RANGES)}）",
            )

        try:
            if scope == "session":
                data, summary_text = self._session_scope(session_id)
            else:
                data, summary_text = self._global_scope(range)
        except Exception as exc:  # noqa: BLE001
            logger.exception("sage_usage 执行失败 (scope=%s)", scope)
            return ToolResult(success=False, error=f"用量查询失败: {exc}")

        # 会话无法解析属于"无法回答"而非"空结果" —— 与上面的参数校验分支
        # 保持一致，用 success=False 让调用方/LLM 能区分。
        if isinstance(data, dict) and "error" in data:
            return ToolResult(success=False, error=str(data["error"]))

        return ToolResult(success=True, content=data, output=summary_text)

    # ------------------------------------------------------------------
    # global 范围
    # ------------------------------------------------------------------

    @staticmethod
    def _global_scope(range_: str):
        from backend.services.usage_tracker import usage_tracker

        summary = usage_tracker.summary_with_range(range_)
        totals = dict(summary.get("totals") or {})
        by_model = list(summary.get("by_model") or [])[:_MAX_MODELS]
        data = {
            "scope": "global",
            "range": range_,
            "totals": totals,
            "by_model": by_model,
            "cache_hit_rate": summary.get("cache_hit_rate"),
            "known_requests": summary.get("known_requests"),
            "unknown_requests": summary.get("unknown_requests"),
            "has_partial_estimates": summary.get("has_partial_estimates"),
        }
        return data, _format_global(data)

    # ------------------------------------------------------------------
    # 会话范围
    # ------------------------------------------------------------------

    @staticmethod
    def _session_scope(session_id: Optional[str]):
        if not session_id:
            from backend.tools.context import current_tool_context

            ctx = current_tool_context()
            session_id = ctx.session_id if ctx is not None else None
        if not session_id:
            return (
                {"scope": "session", "error": "当前调用没有绑定会话，请显式传 session_id"},
                "无法确定会话：当前工具执行上下文无 session_id，请显式传 session_id 参数。",
            )

        from backend.services.usage_tracker import usage_tracker

        raw = usage_tracker.session_summary(session_id)
        # 只保留对 LLM 有意义的字段，避免把内部结构整包透出
        keep = (
            "session_id",
            "requests",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cached_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "estimated_cost_usd",
            "cache_hit_rate",
            "latency_stats",
            "model_latency_stats",
        )
        data = {"scope": "session", **{k: raw.get(k) for k in keep if k in raw}}
        return data, _format_session(data)


def _fmt_cost(value: Any) -> str:
    """成本展示：None 表示定价未知，不能静默显示 $0.0000。"""
    if value is None:
        return "未知（模型定价缺失）"
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _format_global(data: Dict[str, Any]) -> str:
    t = data["totals"]
    lines: List[str] = [
        f"Sage 全局用量（{data['range']}）:",
        f"  请求数={t.get('requests', 0)}, 输入 tokens={t.get('prompt_tokens', 0)}, "
        f"输出 tokens={t.get('completion_tokens', 0)}, "
        f"估算成本={_fmt_cost(t.get('estimated_cost_usd'))}",
    ]
    hit = data.get("cache_hit_rate")
    if hit is not None:
        lines.append(f"  cache 命中率={float(hit) * 100:.1f}%")
    unknown = data.get("unknown_requests") or 0
    if unknown:
        lines.append(f"  注意: {unknown} 次请求的模型定价未知，成本为部分估算")
    by_model = data.get("by_model") or []
    if by_model:
        lines.append("  按模型:")
        for m in by_model:
            lines.append(
                f"    - {m.get('model')}: {m.get('requests', 0)} 次, "
                f"输入={m.get('prompt_tokens', 0)}, 输出={m.get('completion_tokens', 0)}, "
                f"成本={_fmt_cost(m.get('estimated_cost_usd'))}"
            )
    return "\n".join(lines)


def _format_session(data: Dict[str, Any]) -> str:
    if "error" in data:
        return data["error"]
    lines: List[str] = [
        f"当前会话用量（session={data.get('session_id')}）:",
        f"  请求数={data.get('requests', 0)}, 输入 tokens={data.get('prompt_tokens', 0)}, "
        f"输出 tokens={data.get('completion_tokens', 0)}, "
        f"总 tokens={data.get('total_tokens', 0)}, "
        f"估算成本={_fmt_cost(data.get('estimated_cost_usd'))}",
    ]
    hit = data.get("cache_hit_rate")
    if hit is not None:
        lines.append(f"  cache 命中率={float(hit) * 100:.1f}%")
    latency = data.get("latency_stats") or {}
    if latency.get("avg_latency_ms") is not None:
        lines.append(
            f"  延迟: avg={latency.get('avg_latency_ms'):.0f}ms, "
            f"p95={latency.get('p95_latency_ms') or 0:.0f}ms, "
            f"max={latency.get('max_latency_ms') or 0:.0f}ms"
        )
    return "\n".join(lines)
