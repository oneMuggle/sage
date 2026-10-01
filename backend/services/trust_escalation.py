"""渐进式授权（progressive delegation）—— P2-5。

问题：用户在一次会话里反复批准同一类常规操作（``edit_file``、``write_file``
…），每次都弹窗点头。主流 coding agent（Claude Code / Codex）的解法是
**progressive delegation**：连续批准 N 次后，对该工具自动放行。

为什么这不是「AutoApproveEnforcer 的重复」：
``backend/orchestration/subagent_approval.py`` 的 autopilot 是 run 级的
**二值开关**（用户显式勾「子代理自动批准非危险工具」），覆盖全部子代理、
与用户的历史判断无关。本模块是**会话级、由用户自己的批准历史驱动**的，
且默认关闭。

安全不变式（与 autopilot 保持一致，且更严）：

1. **默认关闭**。未显式开启时，行为与本模块存在前完全一致。未经同意的
   自动放行是 PHILOSOPHY 明令禁止的黑盒决策。
2. **deny 永远胜出**。本包装器只在 base 判定 ``needs_approval`` 时改写，
   绝不把 deny 变成 allow。
3. **只认人工批准**。``answered_by != 'gui'`` 的决策（auto / trust / timeout）
   不计入连续次数 —— 用自动放行喂自动放行会自我强化，一次误配即滚成全自动。
4. **遇拒绝即重置**。连续性从最近一条往回数，见 repo 的实现。
5. **破坏性 / 可疑命令永不自动放行**（bash 安全网语义保留）。
6. **工作区边界类升级永不自动放行**（fail-closed 语义保留）。
7. **无法静态评估风险的执行面工具保守转人工**（skill / repl / kill_shell）。
8. **查询失败降级为继续人工审批**。宁可多问一次，不可静默放行。
9. **每次自动放行都落库**（``answered_by='trust'``），事后可在审计台账里
   区分「用户点的」和「系统放行的」。

py38 兼容（release/win7 线）：本文件不使用 ``X | Y`` 类型语法、
``zip(strict=)``、``datetime.UTC`` 或构造期 ``asyncio.Lock()``。
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

#: 边界类升级的 reason 特征 —— 命中即保留人工审批（与 autopilot 同一口径）。
_BOUNDARY_REASON_MARKERS = ("工作区外", "边界")

#: 自动放行标记后缀 —— 供审计/时间线辨认放行来源。
_TRUST_REASON_SUFFIX = "（连续批准自动放行 trust）"

#: 默认阈值。3 次是「确实是常规操作」与「手滑连点」之间的折中。
DEFAULT_TRUST_THRESHOLD = 3

#: settings 键（沿用 orch_settings 的 KV 命名习惯）
SETTINGS_KEY_ENABLED = "trust_escalation_enabled"
SETTINGS_KEY_THRESHOLD = "trust_escalation_threshold"


class TrustEscalationEnforcer:
    """``needs_approval`` 的信任升级包装器（duck-type ``PermissionEnforcer``）。

    与 ``AutoApproveEnforcer`` 的区别：放行依据是**用户自己的连续人工批准
    历史**，而不是一个二值开关；且默认关闭。
    """

    def __init__(self, base: PermissionEnforcer, threshold: int = DEFAULT_TRUST_THRESHOLD) -> None:
        self._base = base
        self.threshold = max(1, int(threshold))

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

        # 边界类升级永不自动放行。
        reason = decision.reason or ""
        if any(marker in reason for marker in _BOUNDARY_REASON_MARKERS):
            return decision

        # 执行面工具：只有能验证为非危险命令才考虑自动放行。
        if classify_tool(tool_name) is ToolCapability.EXECUTE:
            command = (args or {}).get("command")
            if not (isinstance(command, str) and command.strip()):
                return decision
            validation = validate_bash(command)
            if validation.risk in (BashRisk.DESTRUCTIVE, BashRisk.SUSPICIOUS):
                return decision

        # 到这里才查信任：前面的安全网判定失败会直接 return，不会走到 DB。
        session_id = _current_session_id()
        if not session_id:
            return decision
        approved_times = _consecutive_approvals(session_id, tool_name)
        if approved_times < self.threshold:
            return decision

        _record_trust_release(tool_name, approved_times)
        return PermissionDecision(
            allowed=True,
            needs_approval=False,
            reason=(
                "{reason}{suffix}（你已连续批准该操作 {n} 次）".format(
                    reason=reason,
                    suffix=_TRUST_REASON_SUFFIX,
                    n=approved_times,
                )
            ),
        )


def _current_session_id() -> Optional[str]:
    """取当前工具执行上下文的 session_id；取不到返回 ``None``（保守）。"""
    try:
        from backend.tools.context import current_tool_context

        ctx = current_tool_context()
        return ctx.session_id if ctx is not None else None
    except Exception as exc:  # noqa: BLE001 — 取不到就继续问人
        logger.debug("trust 升级取 session 失败（忽略）: %s", exc)
        return None


def _consecutive_approvals(session_id: str, tool_name: str) -> int:
    """连续人工批准次数；查询失败一律 0（fail-safe = 继续人工审批）。"""
    try:
        from backend.data.approval_decision_repo import ApprovalDecisionRepository

        return ApprovalDecisionRepository().consecutive_gui_approvals(session_id, tool_name)
    except Exception as exc:  # noqa: BLE001 — 降级为逐次审批
        logger.warning("trust 升级计数失败，降级为逐次审批: %s", exc)
        return 0


def _record_trust_release(tool_name: str, approved_times: int) -> None:
    """自动放行落库，全吞降级 —— 审计写失败不阻塞工具执行。"""
    try:
        from backend.data.approval_decision_repo import ApprovalDecisionRepository
        from backend.tools.context import current_tool_context

        ctx = current_tool_context()
        ApprovalDecisionRepository().append(
            tool_name=tool_name,
            approved=True,
            answered_by="trust",
            session_id=ctx.session_id if ctx is not None else None,
            risk="trusted",
        )
        logger.info(
            "渐进式授权自动放行 tool=%s（连续人工批准 %d 次）", tool_name, approved_times
        )
    except Exception as exc:  # noqa: BLE001 — 审计降级不阻塞执行
        logger.debug("trust 放行落库失败（忽略）tool=%s: %s", tool_name, exc)


def load_trust_policy() -> tuple:
    """读取渐进式授权策略 ``(enabled, threshold)``；读取失败 → 关闭。

    与 ``load_enforcer_from_settings`` 同源（``SettingsRepository``），保持
    权限相关读取只有一条路径。
    """
    try:
        from backend.data.settings_repo import SettingsRepository

        repo = SettingsRepository()
        raw_enabled = repo.get(SETTINGS_KEY_ENABLED)
        raw_threshold = repo.get(SETTINGS_KEY_THRESHOLD)
        enabled = str(raw_enabled or "").strip().lower() in ("1", "true", "on", "yes")
        try:
            threshold = int(raw_threshold)
        except (TypeError, ValueError):
            threshold = DEFAULT_TRUST_THRESHOLD
        return enabled, max(1, threshold)
    except Exception as exc:  # noqa: BLE001 — 读取失败 = 保持关闭
        logger.warning("渐进式授权策略读取失败，保持关闭: %s", exc)
        return False, DEFAULT_TRUST_THRESHOLD


def build_trust_enforcer(base: PermissionEnforcer) -> Optional[PermissionEnforcer]:
    """按策略决定是否包装；未启用返回 ``None``（= 保持既有逐次审批）。"""
    enabled, threshold = load_trust_policy()
    if not enabled:
        return None
    return TrustEscalationEnforcer(base, threshold=threshold)


__all__ = [
    "TrustEscalationEnforcer",
    "build_trust_enforcer",
    "load_trust_policy",
    "DEFAULT_TRUST_THRESHOLD",
    "SETTINGS_KEY_ENABLED",
    "SETTINGS_KEY_THRESHOLD",
    "_TRUST_REASON_SUFFIX",
]
