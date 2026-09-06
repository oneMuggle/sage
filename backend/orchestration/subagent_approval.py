"""编排子代理自动批准包装器（live-events P1 分级信任）。

背景：编排子代理默认继承全局权限模式（``workspace_write``），EXECUTE
类工具（bash/repl/skill）逐次审批。审批请求此前不转发前端（黑洞，300s
fail-closed），即便转发后，逐次人工确认也会让并行编排退化成逐个点头。
本模块提供 run 级"自动批准非危险工具"模式（autopilot）：

- ``AutoApproveEnforcer`` 包装 base ``PermissionEnforcer`` —— **规则层、
  模式矩阵、deny 语义全部复用 base**，只在 base 判定 ``needs_approval``
  时做二次风险裁决：非危险（非破坏性/非可疑/边界合法）→ 自动放行，
  危险 → 保留审批（经 SubagentEventSink 转发人工）。
- 不发明第二套风险分级：执行面命令风险复用 ``validate_bash``；写边界
  升级（写工作区外 / 边界解析失败 fail-closed）一律保留人工。

安全不变式：
- deny 永远胜出（base 已裁决，包装器不改写）；
- 破坏性/可疑命令永不自动批准（bash 安全网语义保留）；
- 工作区边界类升级永不自动批准；
- 无法评估风险的执行面工具（无 command 参数，如 skill/repl）保守转人工。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.tools.bash_validation import BashRisk, validate_bash
from backend.tools.permissions import (
    PermissionDecision,
    PermissionEnforcer,
    ToolCapability,
    classify_tool,
)

logger = logging.getLogger(__name__)

#: 边界类升级的 reason 特征 —— 命中即保留人工审批（fail-closed 语义保留）。
_BOUNDARY_REASON_MARKERS = ("工作区外", "边界")

#: 自动批准标记后缀 —— 供审计/时间线辨认放行来源。
_AUTO_REASON_SUFFIX = "（编排自动批准 auto）"


class AutoApproveEnforcer:
    """``needs_approval`` 的二次风险裁决包装器（duck-type PermissionEnforcer）。

    agent 循环只依赖 ``check(tool_name, args)``（``agent.py`` enforcer.check
    分发点）；``mode`` / ``rules`` 属性委托 base，保持诊断接口兼容。
    """

    def __init__(self, base: PermissionEnforcer) -> None:
        self._base = base

    @property
    def mode(self):  # noqa: ANN201 — 与 base 同型
        return self._base.mode

    @property
    def rules(self):  # noqa: ANN201 — 与 base 同型
        return self._base.rules

    def check(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> PermissionDecision:
        decision = self._base.check(tool_name, args or {})
        if not decision.needs_approval:
            # allow / deny 原样保留 —— deny 永远胜出。
            return decision

        # 边界类升级（写工作区外 / 边界解析失败）永不自动批准。
        reason = decision.reason or ""
        if any(marker in reason for marker in _BOUNDARY_REASON_MARKERS):
            return decision

        # 执行面工具：只有能验证为非危险命令才自动批准。
        if classify_tool(tool_name) is ToolCapability.EXECUTE:
            command = (args or {}).get("command")
            if not (isinstance(command, str) and command.strip()):
                # skill / repl / kill_shell 等无法静态评估风险 → 保守转人工。
                return decision
            validation = validate_bash(command)
            if validation.risk in (BashRisk.DESTRUCTIVE, BashRisk.SUSPICIOUS):
                return decision

        return PermissionDecision(
            allowed=True,
            needs_approval=False,
            reason=f"{reason}{_AUTO_REASON_SUFFIX}",
        )


def build_subagent_enforcer(approval_mode: str) -> Optional[PermissionEnforcer]:
    """按审批模式构造子代理 enforcer；非 auto / 构造失败返回 ``None``。

    ``None`` = 子代理走默认路径（run_loop 从 settings 现读现建）。
    base enforcer 从 settings 读取（含用户 remember 规则），读取失败降级
    ``None``（保守回落"逐次审批"而非放行）。
    """
    if approval_mode != "auto":
        return None
    try:
        from backend.tools.permissions import load_enforcer_from_settings

        base = load_enforcer_from_settings()
        return AutoApproveEnforcer(base)
    except Exception as exc:  # noqa: BLE001 — 失败保守回落人工审批
        logger.warning("AutoApprove enforcer 构造失败，回落逐次审批: %s", exc)
        return None


__all__ = ["AutoApproveEnforcer", "build_subagent_enforcer", "_AUTO_REASON_SUFFIX"]
