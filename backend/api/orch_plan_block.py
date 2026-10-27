"""编排计划块 —— 注入 conductor system prompt 的「已确认计划」段落。

2026-10-27 从 legacy_routes.py 拆出：该文件已是 2500+ 行的 legacy 巨石，
这块内聚的编排计划逻辑（哨兵常量 + 计划块构建 + 确认后回读）独立成模块，
使 legacy_routes.py 降回 architecture-baseline 登记行数以下。

调用时机约束见 build_orch_plan_block 的 docstring。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: override 路径（"按计划执行（编排）"）没有 decompose 阶段的 LLM 推理，
#: plan_json 的 reasoning 用这个哨兵占位。它是后端内部标记而非给人看的文字
#: —— task_plan 事件下发给前端前必须过滤成空串，否则 PlanCard 的"规划思路"
#: 折叠区会把 plan_override 原文当拆解思路展示给用户。
PLAN_OVERRIDE_REASONING = "plan_override"


def build_orch_plan_block(plan_items: List[Dict[str, Any]]) -> str:
    """编排计划块 —— 注入 conductor system prompt 的"已确认计划"段落。

    必须在确认门控**之后**调用：计划卡在确认窗口内可被 update_plan 改写
    （用户编辑 goal / 自然语言修订），提前注入会让 conductor 执行过期计划。
    """
    plan_block = "\n".join(
        f"- {i}. [{it.get('agent_id', 'primary')}] {it.get('goal', '')}"
        for i, it in enumerate(plan_items, 1)
    )
    return (
        "\n\n以下为已确认的任务计划，请调用 dispatch_subagents "
        "工具并行执行这些子任务（可合并/调整）。不要复述计划，直接执行。\n"
        + plan_block
        # 进度可视化 P0-2 后置 (2026-08-12): 强化"必须全量执行完
        # 才汇总"约束。dispatch_subagents 每次调用可能只派发部分
        # 子任务（分批/合并），若聚合头只反映"本批已收到 X/X"，
        # LLM 可能误以为全部完成而提前总结。这里显式给出总数 N，
        # 要求必须等到 N 个全部有结果才输出最终汇总。
        + "\n\n必须执行完计划中的全部"
        + str(len(plan_items))
        + " 个子任务，等到所有子任务都返回结果后，才能输出最终汇总。"
        "若本次 dispatch 只执行了部分子任务，请继续调用工具执行剩余任务，"
        "不要提前给出结论。"
        # RT11 (round7): 失败处理指令 —— 此前 conductor 只被告知
        # "必须全部执行完"，失败子任务无任何再规划指引，唯一出路
        # 是 LLM 对聚合文本的自由裁量。
         + "\n\n子任务失败时的处理方式：阅读该任务的失败原因文本，"
        "判断是可修复错误（参数不当、依赖文件缺失、路径错误等）还是"
        "不可行任务。可修复的，调整 goal 描述或改派更合适的 agent 重新"
        "派发该工作（可派发新任务，或用 retry_of 重派并继承现场）；"
        "不可行的，在最终汇总中说明原因。"
        "不要原样重派已经失败的同一任务。"
        # BD4 (round15): 后台工作流指引 —— background=true 派发后
        # 立即返回，期间可先做其他工作，再 collect_subagents 收取。
        # BD5 (round16): 补充非阻塞快照与提前汇总策略。
         + "\n\n当某些子任务耗时较长而你希望先推进其他工作时，可在 "
        "dispatch_subagents 传 background=true 后台派发（立即返回），"
        "期间执行你自己的其他工具调用，之后调用 collect_subagents "
        "获取聚合结果；collect 超时只表示还没跑完，任务板仍在推进，"
        "可再次 collect。"
        "collect 可传 wait=false 立即获取各子任务当前状态与结果"
        "预览快照——若已有信息足以支撑最终结论，可据此提前汇总，"
        "无需等待全部子任务完成。"
        # RP1 (round34, 2026-09-19): re-plan 工具族指引 ——
        # 此前 conductor 只能靠上段"失败处理指令"做任务级微调，
        # 无法主动调整计划结构（改目标/取消/加任务）。
         + "\n\n发现原计划不再适用时可主动调整计划，有三个工具："
        "\n- update_pending_task：修改尚未派发任务的 goal 或执行"
        "角色，参数 task_id 必填、goal 与 agent_id 至少给一个。"
        "\n- cancel_pending_task：取消不再需要的任务，参数 task_id "
        "必填、reason 可选。未派发的直接移出计划，已派发仍在排队的"
        "会被跳过，运行中的会被软中断；取消后请勿重派该任务。"
        "\n- add_task_to_plan：把新发现的工作加入计划，参数 task_id "
        "/ goal + agent_id 必填，depends_on 可选且只能引用已存在的"
        "task_id。添加后调用 dispatch_subagents 派发即可执行。"
        "\n任务失败时不要原样重派 —— 先判断该改目标、换角色、取消，"
        "还是补充新任务。"
    )


def load_confirmed_plan_items(run_id: str) -> Optional[List[Dict[str, Any]]]:
    """确认门控通过后回读权威计划 —— 计划卡编辑/修订已落库。

    返回 None 表示读库失败或计划为空，调用方回落内存 plan_items（原行为）。
    """
    try:
        from backend.data.orch_run_repo import OrchRunRepository

        run = OrchRunRepository().get(run_id)
        if run is None or not run.plan_json:
            return None
        raw = json.loads(run.plan_json)
        tasks = raw.get("tasks") if isinstance(raw, dict) else None
        if not isinstance(tasks, list):
            return None
        items = [dict(t) for t in tasks if isinstance(t, dict) and t.get("task_id")]
        return items or None
    except Exception as exc:  # noqa: BLE001 — 回读失败不影响主流程
        logger.warning("确认后回读计划失败 run=%s err=%s", run_id, exc)
        return None
