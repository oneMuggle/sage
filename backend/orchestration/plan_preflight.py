"""``plan_preflight`` — 编排计划前置（需求澄清 + 侦察先行，2026-09-19）。

multi 编排在 LLM 拆解（``Planner.decompose_request``）之前补两步，补齐
复杂任务管线"确认需求 / 调研"两个断点（对照 Claude Code plan mode 与
Deep Research 的"先澄清、先侦察再规划"）：

1. **需求澄清（clarify）**：单次 LLM 调用同时判定目标是否有显著歧义并
   生成结构化问题（≤3 问）；有则经聊天流 ``ask_user_question`` 事件 +
   全局 ``UserQuestionGate`` 向用户提问——完整复用 M2 part B 的前端通道
   （QuestionDialog 渲染、``POST /api/v1/questions/{id}/answer`` 应答回流），
   零前端改动。
2. **事实侦察（scout）**：一个低预算只读子代理（agent_tool 同款构建：
   ``SageAgent(bare=True)`` + ``build_readonly_tool_registry``，结构性无写
   工具）快速收集文件/网络/记忆事实，产出分点事实清单。

两步产出合并为 ``{"clarifications": [...], "scout_facts": "..."}`` 注入
planner context，由 ``Planner._build_decomposition_prompt`` 具名渲染。

降级纪律（硬约束）：preflight 是增强不是门槛 —— 总闸/旋钮关闭、无 LLM
配置、歧义判定失败、gate 缺失、提问超时、侦察超时或异常 → 跳过对应步骤，
``run_plan_preflight`` 返回 None（等价于现状 ``context=None``），绝不阻塞
编排。测试确定性：backend/tests/conftest.py 默认 ``SAGE_ORCH_PLAN_PREFLIGHT=0``。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.orchestration.orch_settings import load_orch_settings
from backend.services.question_gate import QuestionRequest, get_question_gate
from backend.tools.ask_user_tool import render_answer_result, validate_ask_user_args
from backend.utils.py_compat import TIMEOUT_ERRORS

logger = logging.getLogger(__name__)

#: 总闸 env（tests conftest setdefault 0）。非法值按开启处理 —— 误配不静默
#: 关闭生产功能。
PREFLIGHT_MASTER_ENV = "SAGE_ORCH_PLAN_PREFLIGHT"

#: 澄清提问等待应答的超时秒数（gate 层 fail-open，超时按未澄清继续）。
CLARIFY_TIMEOUT_ENV = "SAGE_ORCH_CLARIFY_TIMEOUT"
DEFAULT_CLARIFY_TIMEOUT_S = 300.0

#: 侦察墙钟上限（秒）——侦察是拆解前的快速侦察，不是深度调研。
SCOUT_TIMEOUT_ENV = "SAGE_ORCH_SCOUT_TIMEOUT"
DEFAULT_SCOUT_TIMEOUT_S = 120.0

#: 侦察员 ReAct 迭代预算（低于子代理默认 6 —— 侦察要快）。
SCOUT_MAX_ITERATIONS = 4

#: 事实清单注入 planner context 的截断上限（字符）。
SCOUT_FACTS_MAX_CHARS = 4000

#: 单轮澄清最多提问数（防骚扰上限；全局防骚扰由 run_loop 的
#: MAX_CONSECUTIVE_UNANSWERED_QUESTIONS 管辖，这里管单轮生成量）。
MAX_CLARIFY_QUESTIONS = 3

# Matches ```json ... ``` / ``` ... ``` fences some models emit anyway.
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

#: 歧义判定 + 问题生成合并为单次 LLM 调用（省一次往返）。str.replace 注入
#: （非 .format()），与 _classify_orchestration_prompt 同款防大括号炸裂。
_CLARIFY_PROMPT = """你是需求澄清助手。判断以下目标在拆解执行前是否存在会显著影响执行方案的歧义（范围不清/交付格式不明/验收标准缺失/关键约束冲突）。

目标: {message}

规则:
- 只在歧义"显著影响执行方案"时才提问；常识可默认的细节不要问。
- 最多 {max_q} 个问题；每个问题 2-4 个选项，选项要具体、可直接点选。

只返回 JSON（无 markdown 围栏、无多余文本）:
{{"need_clarify": true, "questions": [{{"question": "完整问题文本", "header": "短标签", "multi_select": false, "options": [{{"label": "选项", "description": "说明"}}]}}]}}
无歧义时返回: {{"need_clarify": false, "questions": []}}"""

#: 侦察员 system prompt —— 只读、快、事实导向。
_SCOUT_SYSTEM_PROMPT = (
    "你是规划侦察员。用只读工具快速收集与目标相关的关键事实：工作区文件"
    "结构、相关文档要点、记忆中的相关偏好与历史、必要的网络资料。纪律："
    "只读不写；少量几轮工具调用即可；最后输出分点事实清单（每条一句话并"
    "注明来源），不做方案建议，不写任何文件。"
)

#: render_answer_result 的未应答软文案标记（Escape 空提交 / 超时共用）。
UNANSWERED_MARKER = "用户未回答"


def preflight_master_enabled() -> bool:
    """总闸：env ``SAGE_ORCH_PLAN_PREFLIGHT`` 显式为 0/false 时关闭。"""
    return os.environ.get(PREFLIGHT_MASTER_ENV, "1").strip().lower() not in ("0", "false")


def _clarify_timeout_s() -> float:
    raw = os.environ.get(CLARIFY_TIMEOUT_ENV, "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_CLARIFY_TIMEOUT_S


def _scout_timeout_s() -> float:
    raw = os.environ.get(SCOUT_TIMEOUT_ENV, "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_SCOUT_TIMEOUT_S


async def _emit(emit: Optional[Callable[[Dict[str, Any]], Awaitable[None]]], event: Dict[str, Any]) -> None:
    """向 producer 队列推事件；emit 缺失/队列异常一律吞掉（透明度事件不阻塞主流程）。"""
    if emit is None:
        return
    try:
        await emit(event)
    except Exception:  # noqa: BLE001 — 事件推送失败绝不阻断 preflight
        logger.debug("plan_preflight emit 失败: %s", event.get("state"), exc_info=True)


async def run_plan_preflight(
    message: str,
    emit: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> Optional[Dict[str, Any]]:
    """编排拆解前置：澄清 + 侦察，返回 planner context 增量（或 None）。

    本函数**永不抛错**：任何一层失败都降级为跳过该步；两步皆无产出时
    返回 None（调用方等价于现状 ``decompose_request(message)``）。

    Args:
        message: 用户原始目标。
        emit: 事件推送协程（producer 传 ``entry.queue.put``）——推
            ``orch_preflight`` 进度事件与 ``ask_user_question`` 提问事件。
    """
    try:
        if not message.strip():
            return None
        if not preflight_master_enabled():
            return None
        settings = load_orch_settings()
        if not settings.plan_preflight_enabled:
            return None

        # 惰性导入：llm_factory 读 settings DB，保持与 Planner 同款装配路径。
        from backend.orchestration.llm_factory import build_llm_client_from_settings

        client = build_llm_client_from_settings()
        if client is None:
            logger.info("plan_preflight: 无 LLM 配置，跳过澄清/侦察")
            return None

        result: Dict[str, Any] = {}

        clarifications = await _clarify(client, message, emit)
        if clarifications:
            result["clarifications"] = clarifications

        if settings.plan_scout_enabled:
            facts = await _scout(client, message, emit, clarifications)
            if facts:
                result["scout_facts"] = facts

        return result or None
    except Exception:  # noqa: BLE001 — preflight 永不阻塞编排
        logger.warning("plan_preflight 异常，跳过", exc_info=True)
        return None


async def _clarify(
    client: Any,
    message: str,
    emit: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
) -> List[str]:
    """歧义判定 + 提问 + 收集应答；返回澄清结论文本列表（空 = 无澄清）。"""
    gate = get_question_gate()
    if gate is None:
        # gate 未装配（极早启动/测试隔离场景）→ 按无人应答处理，不挂起。
        return []

    await _emit(emit, {"state": "orch_preflight", "phase": "clarify"})

    prompt = _CLARIFY_PROMPT.replace("{message}", message).replace(
        "{max_q}", str(MAX_CLARIFY_QUESTIONS)
    )
    try:
        raw = await client.complete(prompt)
    except Exception as exc:  # noqa: BLE001 — 判定失败必须跳过，绝不阻塞
        logger.warning("plan_preflight 澄清判定 LLM 调用失败，跳过: %s", exc)
        return []

    questions = _parse_clarify_response(raw)
    if not questions:
        return []

    conclusions: List[str] = []
    timed_out = False
    for args in questions[:MAX_CLARIFY_QUESTIONS]:
        req = QuestionRequest.create(
            question=args["question"],
            options=args["options"],
            header=args.get("header"),
            multi_select=bool(args.get("multi_select", False)),
        )
        # 与 run_loop 的 ask_user_question 事件同形 —— 前端 QuestionDialog
        # 既有通道渲染并应答（POST /api/v1/questions/{id}/answer）。
        await _emit(emit, {"state": "ask_user_question", "user_question": req.to_dict()})
        answer = await gate.request(req, timeout=_clarify_timeout_s())
        if answer.answered_by == "timeout":
            timed_out = True
            continue
        rendered = str(render_answer_result(answer.answers, answer.custom).content)
        if UNANSWERED_MARKER in rendered:
            continue  # Escape 空提交 → 视为未澄清
        conclusions.append(f"问: {req.question}\n{rendered}")

    if timed_out and not conclusions:
        conclusions.append(
            "用户未应答澄清提问（超时）。请按合理默认值执行，并在计划中写明关键假设。"
        )
    return conclusions


def _parse_clarify_response(raw: Any) -> List[Dict[str, Any]]:
    """解析 LLM 澄清响应 → 经 ``validate_ask_user_args`` 校验的问题列表。

    任何畸形（非 JSON / need_clarify 非真 / 问题参数不合法）→ 空列表，
    调用方跳过澄清。
    """
    if not isinstance(raw, str) or not raw.strip():
        return []
    text = _CODE_FENCE_RE.sub("", raw.strip()).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict) or not data.get("need_clarify"):
        return []
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list):
        return []

    valid: List[Dict[str, Any]] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        if validate_ask_user_args(item) is not None:
            continue
        valid.append(item)
    return valid


async def _scout(
    client: Any,
    message: str,
    emit: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
    clarifications: List[str],
) -> str:
    """只读侦察：产出分点事实清单（截断至 SCOUT_FACTS_MAX_CHARS，失败为空）。"""
    await _emit(emit, {"state": "orch_preflight", "phase": "scout"})

    goal = message
    if clarifications:
        bullets = "\n".join(f"- {item}" for item in clarifications)
        goal = f"{message}\n\n用户澄清结论（侦察时一并核实）:\n{bullets}"

    try:
        facts = await asyncio.wait_for(
            _run_scout_agent(client, goal), timeout=_scout_timeout_s()
        )
    except TIMEOUT_ERRORS:
        logger.warning(
            "plan_preflight 侦察超时（%ss），跳过事实注入", _scout_timeout_s()
        )
        return ""
    except Exception as exc:  # noqa: BLE001 — 侦察失败不阻塞拆解
        logger.warning("plan_preflight 侦察失败，跳过: %s", exc)
        return ""
    return (facts or "").strip()[:SCOUT_FACTS_MAX_CHARS]


async def _run_scout_agent(client: Any, goal: str) -> str:
    """驱动只读侦察子代理到完成，返回最终答案文本。

    构建方式与 agent_tool 的子代理一致：``SageAgent(bare=True)`` 跳过记忆
    栈与全量注册表，结构性换装只读注册表；LLM client 注入（生产为
    settings 装配，测试可 monkeypatch 本函数整体替换）。不镜像 Task/Lane
    ——侦察发生在 run 存在之前，不污染编排历史。

    Raises:
        任何异常向上抛出，由 ``_scout`` 统一兜底（含 wait_for 取消）。
    """
    # 惰性导入：backend.core.legacy.agent 反向依赖 backend.tools，模块顶层
    # 导入会成环（agent_tool 同款注释）。
    from backend.core.legacy.agent import SageAgent
    from backend.tools.agent_tool import (
        _cleanup_subagent_workspace,
        build_readonly_tool_registry,
    )

    subagent = SageAgent(bare=True)
    registry = build_readonly_tool_registry()
    subagent.tool_registry = registry
    subagent._owned_workspace_root = getattr(registry, "_owned_workspace_root", None)
    subagent.llm_client = client

    messages = [
        {"role": "system", "content": _SCOUT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"为以下目标的任务拆解做侦察：\n{goal}\n\n"
                "输出不超过 10 条关键事实，每条一句话并注明来源。"
            ),
        },
    ]

    try:
        answer = ""
        async for event in subagent.run_loop(messages, max_iterations=SCOUT_MAX_ITERATIONS):
            state = getattr(event, "state", None)
            state_value = getattr(state, "value", state)
            if state_value == "done":
                answer = event.content or ""
                break
            if state_value == "failed":
                break
        return answer
    finally:
        _cleanup_subagent_workspace(getattr(subagent, "_owned_workspace_root", None))


__all__ = [
    "CLARIFY_TIMEOUT_ENV",
    "DEFAULT_CLARIFY_TIMEOUT_S",
    "PREFLIGHT_MASTER_ENV",
    "SCOUT_TIMEOUT_ENV",
    "preflight_master_enabled",
    "run_plan_preflight",
]
