"""M1.1 ``sage_self_status`` 工具 —— 一次性聚合 8 维运行时状态。

薄包装层，把 ``backend.services.self_status.gather_self_status`` 暴露给
LLM。工具本身 ``RiskClass.READ``，不进 ``SELF_MODIFY_TOOLS``（只读操作，
默认 WORKSPACE_WRITE 模式下也放行）。

对应 Claude Code 的 ``/status`` 命令。与 M1.2 ``read_sage_config`` 新增的
``self`` section 共享同一份取数逻辑。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.services import self_status as self_status_service
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class SageSelfStatusTool(BaseTool):
    """一次返回 Sage 运行时 8 维状态（版本 / 实际生效模型 / 权限模式 /
    MCP 清单 / 插件清单 / 今日用量 / 健康 / 上下文占用）。"""

    risk: RiskClass = RiskClass.READ

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="sage_self_status",
            description=(
                "一次性获取 Sage 当前运行状态，包括：版本、实际生效模型与端点、"
                "权限模式、MCP 服务器清单、插件清单、今日用量与估算成本、后端健康、"
                "上下文占用。用于快速回答'我现在用的什么模型'、'今天花了多少钱'、"
                "'MCP 是否在线'等问题。部分维度加载失败时该维度返回 error 字段，"
                "其他维度不受影响。"
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        data = self_status_service.gather_self_status()
        summary_lines = self._build_summary(data)
        return ToolResult(
            success=True,
            content=data,
            output="\n".join(summary_lines),
        )

    @staticmethod
    def _build_summary(data: Dict[str, Any]) -> List[str]:
        lines: List[str] = []
        lines.append(f"【版本】{data.get('version', 'unknown')}")

        model = data.get("effective_model", {})
        if "error" in model:
            lines.append(f"【实际生效模型】错误: {model['error']}")
        else:
            lines.append(
                f"【实际生效模型】{model.get('model')} "
                f"(provider={model.get('provider')}, "
                f"endpoint={model.get('endpoint_name') or model.get('endpoint_id')})"
            )

        lines.append(f"【权限模式】{data.get('permission_mode', 'unknown')}")

        mcp = data.get("mcp", [])
        if isinstance(mcp, dict) and "error" in mcp:
            lines.append(f"【MCP 服务器】错误: {mcp['error']}")
        else:
            entries = [
                f"{s.get('name')}(state={s.get('state')}, tools={s.get('tool_count')})"
                for s in mcp
            ]
            lines.append(f"【MCP 服务器】共 {len(mcp)} 个: {'; '.join(entries) or '(无)'}")

        plugins = data.get("plugins", [])
        if isinstance(plugins, dict) and "error" in plugins:
            lines.append(f"【插件】错误: {plugins['error']}")
        else:
            entries = [
                f"{p.get('name')}@{p.get('version')}({p.get('status')})"
                for p in plugins
            ]
            lines.append(f"【插件】共 {len(plugins)} 个: {'; '.join(entries) or '(无)'}")

        usage = data.get("usage", {})
        if "error" in usage:
            lines.append(f"【今日用量】错误: {usage['error']}")
        elif "today" in usage:
            today = usage["today"]
            lines.append(
                f"【今日用量】请求数={today.get('requests', 0)}, "
                f"输入 tokens={today.get('prompt_tokens', 0)}, "
                f"输出 tokens={today.get('completion_tokens', 0)}, "
                f"估算成本=${today.get('estimated_cost_usd', 0):.4f}"
            )
        else:
            lines.append("【今日用量】(无数据)")

        health = data.get("health", {})
        if health.get("backend_ok"):
            lines.append(f"【健康】后端 OK, DB {'OK' if health.get('db_ok') else '异常'}")
        else:
            lines.append(f"【健康】后端异常: {health.get('error', 'unknown')}")

        return lines
