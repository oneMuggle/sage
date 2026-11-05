"""到达迭代上限时的统一收场：判定轮 / 延长 / 询问 / 停止.

M3 · W2（2026-11-05）：把原先内联在 ``agent.py`` 里的动态预算收尾逻辑
抽成纯函数，让 auto（动态）与 fixed（固定）两种预算模式共用同一条路径：

1. ``extend`` —— 自动模式且进度审计通过（或用户已选择「自动继续」）时
   延长预算并继续。
2. ``final_step`` —— 首次撞上限时先给模型 1 步「收尾机会」：注入
   :data:`FINAL_STEP_NOTICE` system 提醒。模型若直接输出最终答案，走既有
   ``not response.tool_calls → DONE`` 路径，消除「任务完成却报上限」的伪失败。
3. ``ask_user`` —— 判定轮之后模型仍调用工具（确实未完成），且提问闸口
   可用：弹「继续 / 自动继续 / 停止」。
4. ``stop`` —— 其余情况，交回既有 FAILED 事件。

「自动继续」不再绕开审计：即便进入该模式，stuck / no_progress 仍直接
停止（不再询问）。手动「继续」与自动延长由调用方分别计数，手动续跑
不消耗自动延长配额。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from backend.core.legacy.iteration_budget import (
    BudgetAudit,
    BudgetConfig,
    decide_budget,
)

#: 判定轮注入的 system 提醒（与复读提醒同构：直接 append 到 messages）。
FINAL_STEP_NOTICE = (
    "已达当前迭代上限。若任务已经完成，请直接给出最终总结，不要调用工具；"
    "若任务尚未完成，请继续调用最关键的工具。"
)

#: 审计判定「卡住」的阈值，与 iteration_budget 的停止语义保持一致。
STUCK_SCORE = 0.7


@dataclass(frozen=True)
class CeilingPlan:
    """一次「到达上限」检查的处置计划（纯数据，便于单测）。

    Attributes:
        action:     ``extend`` / ``final_step`` / ``ask_user`` / ``stop``。
        next_budget: 延长后的上限（``extend`` / ``ask_user`` 时有意义）。
        reason:     停止/询问原因（stuck / no_progress / extension_limit /
                    hard_cap / fixed_budget / progress）。
        automatic:  ``extend`` 是否由自动预算决策触发。
    """

    action: str
    next_budget: int
    reason: str
    automatic: bool = False


def next_extended_budget(current_budget: int, config: BudgetConfig) -> int:
    """按 extension_ratio 计算下一次延长的上限（夹在 min/max 与硬顶之间）。"""
    chunk = max(
        config.min_extension,
        min(config.max_extension, int(current_budget * config.extension_ratio)),
    )
    return min(config.hard_cap, max(current_budget + 1, current_budget + chunk))


def _audit_blocker(audit: BudgetAudit) -> Optional[str]:
    """「自动继续」模式下仍需强制停止的审计信号。"""
    if audit.stuck_score >= STUCK_SCORE:
        return "stuck"
    if audit.progress_signals <= 0:
        return "no_progress"
    return None


def plan_ceiling(  # noqa: PLR0911 -- 4 个动作 × 自动/手动 × 卡住/健康 分支需要 9 路返回
    *,
    current_budget: int,
    dynamic_active: bool,
    config: BudgetConfig,
    audit: BudgetAudit,
    auto_extensions: int,
    final_step_granted: bool,
    force_extend: bool,
    ask_available: bool,
) -> CeilingPlan:
    """决定到达上限后的下一步动作。

    Args:
        current_budget: 当前生效上限（``effective_max_iterations``）。
        dynamic_active: 是否处于 auto（动态）预算模式。
        config: 预算配置（硬顶 / 延长步长）。
        audit: 当前窗口的进度审计。
        auto_extensions: 已发生的自动延长次数（手动续跑不计入）。
        final_step_granted: 本预算周期是否已发放过判定轮。
        force_extend: 用户是否已选择「自动继续」。
        ask_available: 提问闸口是否可用（可用才允许 ``ask_user``）。
    """
    next_budget = next_extended_budget(current_budget, config)
    can_extend = next_budget > current_budget

    if not final_step_granted:
        if force_extend:
            blocker = _audit_blocker(audit)
            if blocker is None and can_extend:
                return CeilingPlan("extend", next_budget, "progress", True)
            return CeilingPlan(
                "final_step", current_budget, blocker or "hard_cap"
            )
        decision = None
        if dynamic_active:
            decision = decide_budget(
                current_budget, audit, auto_extensions, config
            )
        if decision is not None and decision.action == "extend" and can_extend:
            return CeilingPlan("extend", next_budget, decision.reason, True)
        reason = decision.reason if decision is not None else "fixed_budget"
        if not can_extend:
            reason = "hard_cap"
        return CeilingPlan("final_step", current_budget, reason)

    # 判定轮已用掉且模型仍在调工具 → 确实未完成：能问就问，否则停止。
    if force_extend:
        blocker = _audit_blocker(audit)
        if blocker is not None:
            return CeilingPlan("stop", current_budget, blocker)
        if can_extend:
            return CeilingPlan("extend", next_budget, "progress", True)
        return CeilingPlan("stop", current_budget, "hard_cap")
    decision = None
    if dynamic_active:
        decision = decide_budget(current_budget, audit, auto_extensions, config)
    reason = decision.reason if decision is not None else "fixed_budget"
    if not can_extend:
        reason = "hard_cap"
    if ask_available and can_extend:
        return CeilingPlan("ask_user", next_budget, reason)
    return CeilingPlan("stop", current_budget, reason)


def build_ceiling_question(
    current_budget: int, next_budget: int, reason: str
) -> Dict[str, Any]:
    """构造「继续 / 自动继续 / 停止」提问载荷（前端契约与 ask_user 同构）。"""
    return {
        "question": (
            f"迭代预算已用完（当前上限 {current_budget} 步；"
            f"原因：{reason}）。是否继续执行？"
        ),
        "options": [
            {
                "label": "继续 Continue（再延长一次）",
                "description": f"上限提高到 {next_budget} 步",
            },
            {
                "label": "自动继续 Auto-continue",
                "description": "后续自动延长直到硬顶，不再询问",
            },
            {
                "label": "停止 Stop",
                "description": "保留当前进度并结束本次运行",
            },
        ],
        "header": "迭代预算",
    }


def parse_ceiling_answer(answers: Sequence[str]) -> str:
    """把用户选中的选项 label 解析成 ``auto`` / ``continue`` / ``stop``。

    先匹配「自动 / auto」：选项「自动继续 Auto-continue」同时含「继续」，
    顺序反了会误判成单次继续。
    """
    labels = [str(label).strip().lower() for label in answers]
    if any("自动" in label or "auto" in label for label in labels):
        return "auto"
    if any("继续" in label or "continue" in label for label in labels):
        return "continue"
    return "stop"
