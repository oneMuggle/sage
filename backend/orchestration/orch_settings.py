"""``orch_settings`` — 编排执行参数配置化（P2-9）。

从持久化 ``app_settings`` 读 ``orch`` 段（camelCase keys，与前端
``OrchSettings`` interface 对齐）。旧设置无 orch 段 → 全默认，绝不抛穿。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Optional

from backend.data.settings_repo import SettingsRepository
from backend.domain.tool_policy import DEFAULT_MAX_TOOL_CALLS_PER_RUN

logger = logging.getLogger(__name__)

#: app_settings.orch 段的 camelCase key → OrchSettings 字段名映射。
#: 与前端 src/entities/setting/types.ts 的 OrchSettings interface 对齐。
_RAW_KEYS = {
    "maxConcurrentSubagents": "max_concurrent_subagents",
    "maxAggregateChars": "max_aggregate_chars",
    "maxSubagentResultChars": "max_subagent_result_chars",
    "maxRetries": "max_retries",
    "maxLaneIterations": "max_lane_iterations",
    "maxSubagentIterations": "max_subagent_iterations",
<<<<<<< HEAD
    "maxPrimaryIterations": "max_primary_iterations",
    "maxCoderIterations": "max_coder_iterations",
    "maxReviewerIterations": "max_reviewer_iterations",
    "maxWriterIterations": "max_writer_iterations",
=======
>>>>>>> origin/main
    # 键名必须与前端 OrchSettings.subagentTaskTimeoutS 逐字一致
    # (此前写成 taskTimeoutSeconds, 永远取不到值回落默认 900)。
    "subagentTaskTimeoutS": "subagent_task_timeout_s",
    "scratchRoot": "scratch_root",
    "worktreeIsolation": "worktree_isolation",
    "subagentApprovalMode": "subagent_approval_mode",
    "runTokenBudget": "run_token_budget",
    "runWallClockLimitMinutes": "run_wall_clock_limit_min",
    "maxRetryOfChains": "max_retry_of_chains",
    "maxToolCallsPerRun": "max_tool_calls_per_run",
    "maxIterations": "max_iterations",  # 2026-10-20: primary agent 迭代次数上限
    "planPreflightEnabled": "plan_preflight_enabled",
    "planScoutEnabled": "plan_scout_enabled",
    # 2026-10-27: 计划前置 / Planner 迭代预算（Scout 立即生效；Planner 为
    # 阶段 2.1 ReAct 接入后的预配置）。键名与前端 OrchSettings 逐字一致。
    "maxScoutIterations": "max_scout_iterations",
    "maxPlannerIterations": "max_planner_iterations",
    # 2026-10-28: ask_user_question 工具的可配置限制。键名与前端 OrchSettings 逐字一致。
    "maxConsecutiveUnansweredQuestions": "max_consecutive_unanswered_questions",
    "minOptionsPerQuestion": "min_options_per_question",
    "maxOptionsPerQuestion": "max_options_per_question",
    "maxClarifyQuestionsInPrompt": "max_clarify_questions_in_prompt",
    "maxClarifyQuestionsPerRound": "max_clarify_questions_per_round",
}

#: 迭代预算类 int 字段的下界。0/负值会让 ReAct 循环零次执行
#: (``for i in range(0)``) 立即判定 ``max_iterations_exceeded`` —— 侦察静默
#: 失效（无异常、无日志），比崩溃更难排查。前端 NumberField 有 ``min={1}``
#: 守卫，但 API 可绕过 UI 直写，故后端在此钳制。
#: 注意：``max_iterations``（全局上限）不在此表 —— 其 0 有"按各 agent
#: 分别设置"的独立语义，不能钳。
_INT_MIN_BOUNDS = {
    "max_scout_iterations": 1,
    "max_planner_iterations": 1,
    # 2026-10-28: ask_user_question 限制的下界。0/负值无意义。
    "max_consecutive_unanswered_questions": 1,
    "min_options_per_question": 1,
    "max_options_per_question": 1,
    "max_clarify_questions_in_prompt": 1,
    "max_clarify_questions_per_round": 1,
}


@dataclass
class OrchSettings:
    max_concurrent_subagents: int = 4
    max_aggregate_chars: int = 120 * 1024
    max_subagent_result_chars: int = 50 * 1024
    max_retries: int = 2
    max_lane_iterations: int = 12  # alpha.36 (Bug #2): 8 → 12, 减少"复杂度超上限"误报
    #: 子代理（agent_tool）单次委派的 ReAct 迭代预算。默认 10 与原
    #: ``agent_tool.SUBAGENT_MAX_ITERATIONS`` 常量一致，仅开放可配。
    max_subagent_iterations: int = 10  # alpha.36 (Bug #2): 6 → 10, 减少"复杂度超上限"误报
    #: 主助手（primary profile）迭代上限。legacy_routes.py 调 run_loop 时读取。
    #: 默认 15 与 profiles.py primary profile 对齐。
    max_primary_iterations: int = 15
    #: coder profile 迭代上限。默认 15 与 profiles.py 对齐。
    max_coder_iterations: int = 15
    #: reviewer profile 迭代上限。默认 8 与 profiles.py 对齐。
    max_reviewer_iterations: int = 8
    #: writer profile 迭代上限。默认 5 与 profiles.py 对齐。
    max_writer_iterations: int = 5
    scratch_root: str = "orch_scratch"
    worktree_isolation: bool = False
    #: live-events P1: 新 run 的子代理审批模式默认值 —— "ask"（逐次审批，
    #: 审批请求转发前端）| "auto"（非危险工具自动批准，危险仍转人工）。
    #: run 级可在任务树头部经 ``POST /orch/runs/{id}/approval-mode`` 随时
    #: 切换（仅当前 run 生效，不持久化）。
    subagent_approval_mode: str = "ask"
    #: O2 (2026-09-08): 编排子任务 wall-clock 超时（秒）。0 = 关闭。
    #: 此前子任务只受 profile 迭代上限 × LLM 单请求超时兜底，无墙钟上限 ——
    #: 卡死的子任务会占住并发信号量拖垮整个 run。超时经 asyncio.wait_for
    #: 取消内层协程（与 agent_tool 异步通路的 L12 根修同一语义）。
    subagent_task_timeout_s: int = 900
    #: BU1 (round11): run 级 token 预算（该 run 首次派发起，本 session 累计
    #: total_tokens 上限）。0 = 关闭（默认，保持现状）。触顶后剩余任务经
    #: run 级取消通道收口，conductor 下一批派发被拒（budget_exceeded）。
    run_token_budget: int = 0
    #: BU11 (round21): run 级墙钟上限（分钟）。0 = 关闭（默认）。超限时剩余
    #: 任务经 run 级取消通道收口，归因 wall_clock_exceeded。
    run_wall_clock_limit_min: int = 0
    #: RD14 (round22): 每 run 重派（retry_of）上限 —— 防止 conductor 误判
    #: 时无限链式重派（t3←t2←t1…），token/时长成本失控。超限降级普通任务。
    max_retry_of_chains: int = 10
    #: 单 run 工具调用总数守卫（串行路径 + 并行批次累计）。
    #: 与 ``ToolPolicy.max_tool_calls_per_run`` 同源语义，此处开放 UI 可调。
    #: 默认 100（与 ToolPolicy dataclass 默认一致）。0 = 不限制。
    max_tool_calls_per_run: int = 100
<<<<<<< HEAD
    #: 全局迭代上限（2026-10-20 新增, Win7 适配语义）：
    #: 0 = 回落下方 per-agent 各项独立设置（primary/coder/reviewer/writer）;
    #: >0 = 全局统一上限, legacy_routes.py 用它覆盖 per-agent 细分值。
    #: 与前端 ``OrchSettings.maxIterations`` camelCase 对齐。
    max_iterations: int = 0
=======
    #: Primary agent 迭代次数上限（2026-10-20 新增）。覆盖 AgentProfile 的
    #: 硬编码 max_iterations，允许用户在 UI 中调整。默认 25（与 profiles.py
    #: primary profile 一致）。0 = 使用 profile 默认值。
    max_iterations: int = 25
>>>>>>> origin/main
    #: 计划前置 (2026-09-19): multi 拆解前的澄清+侦察总开关。关闭后拆解
    #: 行为与 2026-09-19 之前完全一致（decompose_request(context=None)）。
    #: env 总闸 ``SAGE_ORCH_PLAN_PREFLIGHT``（tests conftest 置 0）优先于本值。
    plan_preflight_enabled: bool = True
    #: 计划前置 (2026-09-19): 侦察先行单独开关（澄清不受它控制；总闸关闭
    #: 时两者皆停）。侦察有独立墙钟 env ``SAGE_ORCH_SCOUT_TIMEOUT``。
    plan_scout_enabled: bool = True
    #: 2026-10-27: 侦察子代理的 ReAct 迭代预算。此前硬编码为
    #: ``plan_preflight.SCOUT_MAX_ITERATIONS``（4）；开放 UI 可调后由
    #: ``run_plan_preflight`` 透传给 ``_scout``。默认 4 保持既有行为。
    max_scout_iterations: int = 4
    #: 2026-10-27: Planner 的 ReAct 迭代预算 —— 预配置。Planner 当前是单次
    #: ``llm_client.complete``，本值在阶段 2.1 接入只读工具循环后消费。
    #: 默认 8 为总方案建议值；当前不产生任何运行效果。
    max_planner_iterations: int = 8
    # 2026-10-28: ask_user_question 工具的可配置限制。
    #: 连续未应答提问上限。超过后 agent 停止提问并直接推进任务。默认 3。
    max_consecutive_unanswered_questions: int = 3
    #: 每次提问的最小选项数。默认 2。
    min_options_per_question: int = 2
    #: 每次提问的最大选项数。默认 4。
    max_options_per_question: int = 4
    #: 系统提示中的澄清问题数引导（软限制）。默认 2。
    max_clarify_questions_in_prompt: int = 2
    #: 计划前置澄清步骤每轮最多提问数。默认 3。
    max_clarify_questions_per_round: int = 3


def load_orch_settings() -> OrchSettings:
    """从持久化 app_settings 读 orch 段，缺省回落默认值。

    单键读取 + 类型守卫：orch 段是用户可控 JSON，单个坏键只回落该键默认，
    不因一个坏键把整段丢弃（防御 load_orch_settings 上游的脏数据）。
    """
    try:
        raw = SettingsRepository().get_json("app_settings") or {}
        orch = raw.get("orch", {}) if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 — 读配置失败回落默认，绝不抛穿
        orch = {}
    settings = OrchSettings()
    for camel, field_name in _RAW_KEYS.items():
        value = orch.get(camel)
        current = getattr(settings, field_name)
        if value is None:
            continue
        if isinstance(current, bool):
            if not isinstance(value, bool):
                continue
            settings = replace(settings, **{field_name: value})
        elif isinstance(current, int):
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            lower_bound = _INT_MIN_BOUNDS.get(field_name)
            if lower_bound is not None and value < lower_bound:
                logger.warning(
                    "orch 设置 %s=%s 低于下界 %s，已钳制",
                    field_name,
                    value,
                    lower_bound,
                )
                value = lower_bound
            settings = replace(settings, **{field_name: value})
        elif isinstance(current, str) and isinstance(value, str):
            settings = replace(settings, **{field_name: _sanitize_scratch_root(value, current)})
    # live-events P1: 审批模式白名单校验（str 分支通用清洗不覆盖枚举语义）。
    if settings.subagent_approval_mode not in ("ask", "auto"):
        settings = replace(settings, subagent_approval_mode="ask")
    return settings


def _sanitize_scratch_root(value: str, fallback: str) -> str:
    """约束 scratch_root 为安全相对单目录名。

    拒绝绝对路径、含 ``..`` 的穿越、空字符串、以及带路径分隔符的多段
    输入。无效值回落为调用方传入的默认值，保证编排写入目录始终在
    预期数据目录内。
    """
    if not value:
        return fallback
    if PurePath(value).is_absolute():
        return fallback
    if ".." in value.split("/"):
        return fallback
    if "/" in value or "\\" in value:
        return fallback
    return value


#: ``resolve_tool_call_budget`` 最末兜底值 —— 与 ToolPolicy 默认对齐。
#: orch_settings 为工具调用预算单一事实源（env > UI > 默认）。
_DEFAULT_FALLBACK_BUDGET = DEFAULT_MAX_TOOL_CALLS_PER_RUN


def resolve_tool_call_budget(fallback: Optional[int] = None) -> int:
    """解析单-run 工具调用预算 —— 统一优先级链。

    优先级（高→低）：
      1. env ``SAGE_MAX_TOOL_CALLS_PER_RUN``（CI/测试覆盖用）
      2. ``OrchSettings.max_tool_calls_per_run``（UI 可调，持久化到 app_settings）
      3. ``fallback`` 参数（默认 100，与 ``ToolPolicy.DEFAULT_MAX_TOOL_CALLS_PER_RUN``
         保持一致；调用方可传入自己的 ``tool_policy.max_tool_calls_per_run``）

    ``OrchSettings`` 与 env 值必须 ≥ 1 才采纳，否则回落下一层（与
    ``core/legacy/agent.py`` 的 legacy 行为一致；0 不视为"不限"而是回落）。
    永不抛错 —— 任何读取异常回落 ``fallback``。
    """
    default_fallback = fallback if fallback is not None else _DEFAULT_FALLBACK_BUDGET
    # 1) env 覆盖
    raw_env = os.environ.get("SAGE_MAX_TOOL_CALLS_PER_RUN", "").strip()
    if raw_env:
        try:
            env_val = int(raw_env)
            if env_val >= 1:
                return env_val
            logger.warning(
                "env SAGE_MAX_TOOL_CALLS_PER_RUN=%r 非法（<1）,回落 orch/policy",
                raw_env,
            )
        except ValueError:
            logger.warning(
                "env SAGE_MAX_TOOL_CALLS_PER_RUN=%r 非法（非整数）,回落 orch/policy",
                raw_env,
            )
    # 2) UI 可调路径：从 app_settings 读 OrchSettings
    try:
        orch = load_orch_settings()
        orch_val = getattr(orch, "max_tool_calls_per_run", 0)
        if isinstance(orch_val, int) and orch_val >= 1:
            return orch_val
    except Exception as exc:  # noqa: BLE001 — 读设置失败回落 fallback
        logger.debug("OrchSettings 读取失败，回落 fallback: %s", exc)
    # 3) fallback（默认 100）
    return default_fallback
