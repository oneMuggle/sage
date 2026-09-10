"""``SubagentRunner`` — 编排子任务的真实 agent 执行 runner（Wave 1 P0-1/P0-3）。

把子任务执行从 ChatDispatcher 内联的 ``SageAgent.run_loop`` 提升为
``LaneExecutor.agent_runner`` 契约的 callable，使 RecoveryPolicy 重试
在 lane 执行循环中生效。子 agent 以 ``ToolPolicy(workspace_root=scratch_dir)``
构造（P0-3 隔离）：write_file 被 ``file_tool._path_within_workspace`` 边界检查
锁进 scratch 目录，越界写返回 ``path_outside_workspace`` 拒绝。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.agents.profiles import build_system_base, get_enabled_agent
from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentEvent
from backend.domain.tool_policy import ToolPolicy
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.models import Lane
from backend.tools.structured_output_tool import validate_against_schema

logger = logging.getLogger(__name__)

#: 历史重放最多保留的非 system 消息数。
MAX_REPLAY_MESSAGES = 20

#: schema 声明时注入 user message 的硬性格式要求前缀。
_SCHEMA_DIRECTIVE = (
    "\n\n输出格式硬性要求：你的最终回复必须只包含一个符合以下 JSON Schema "
    "的 JSON 对象（可放在代码围栏中），不要输出其他文字。\n"
)


def func_accepts_kwarg(func: Any, kwarg: str) -> bool:
    """探测可调用对象是否接受 ``kwarg`` 关键字参数（O3 兼容层）。

    测试桩/旧扩展常以窄签名替换内部方法 —— 透传新 kwarg 前先探测，
    避免 TypeError 杀死执行。
    """
    import inspect

    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):  # noqa: BLE001 — 内建/ exotic 可调用
        return False
    if kwarg in sig.parameters:
        return True
    return any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )


def run_loop_accepts_session_id(agent: Any) -> bool:
    """探测 agent 的 ``run_loop`` 是否接受 ``session_id`` kwarg（O3）。"""
    return func_accepts_kwarg(agent.run_loop, "session_id")


def run_lane_accepts_backoff(fn: Any) -> bool:
    """探测（可能被 mock.patch 包装的）``run_lane_with_retry`` 是否接受
    ``backoff_secs`` kwarg（RT10 兼容层）。

    ``mock.patch(target, side_effect=fake)`` 产出的 MagicMock 的
    ``inspect.signature`` 恒为 ``(*args, **kwargs)``——直接探测会误判为
    接受任意 kwarg，真实调用仍会落进三参 ``fake`` 的 TypeError。这里
    穿透到 ``side_effect`` 真实函数探测；``side_effect`` 是返回值列表等
    不可调用对象时按原对象探测（Mock 本身吞任意 kwarg，无害）。
    """
    probe = getattr(fn, "side_effect", None)
    target = probe if callable(probe) else fn
    return func_accepts_kwarg(target, "backoff_secs")


def extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出文本提取 JSON object；三种形态依次尝试，失败返回 None。

    优先级：整段即 JSON > ``` 围栏 > 首个 ``{`` 到末个 ``}`` 子串。
    """
    candidate = (text or "").strip()
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    fence_start = candidate.find("```json")
    if fence_start == -1:
        fence_start = candidate.find("```")
    if fence_start != -1:
        body_start = candidate.find("\n", fence_start)
        fence_end = candidate.find("```", fence_start + 3)
        if body_start != -1 and fence_end > body_start:
            try:
                parsed = json.loads(candidate[body_start + 1 : fence_end].strip())
                return parsed if isinstance(parsed, dict) else None
            except ValueError:
                pass
    brace_start = candidate.find("{")
    brace_end = candidate.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            parsed = json.loads(candidate[brace_start : brace_end + 1])
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None
    return None


class SubagentRunner:
    """经 ``LaneExecutor.agent_runner`` 契约执行单个编排子任务。"""

    def __init__(
        self,
        llm_config: Optional[Dict[str, Any]] = None,
        interrupt_event: Optional[asyncio.Event] = None,
        event_sink: Optional[Callable[[AgentEvent], Awaitable[None]]] = None,
        approval_mode: str = "ask",
        session_id: Optional[str] = None,
        context_repo: Optional[Any] = None,
        context_task_id: Optional[str] = None,
    ) -> None:
        self._llm_config = llm_config
        # P0-3 (2026-08-20): 取消事件 —— ChatDispatcher._cancelled 传入，
        # 置位后 watcher 调 child.interrupt()，子 run_loop 在下轮迭代顶部
        # 发 FAILED 终止（P0-1 通道）。
        self._interrupt_event = interrupt_event
        # live-events P0: 子 run_loop 中间事件投影回调（SubagentEventSink）。
        # None = 不转发（老调用方/测试兼容，行为与历史一致）。
        self._event_sink = event_sink
        # live-events P1: "ask"（默认，风险工具逐次审批）| "auto"
        # （非危险工具自动批准，危险仍转人工）。经 build_subagent_enforcer
        # 注入 AutoApproveEnforcer。
        self._approval_mode = approval_mode
        # O3 (2026-09-08): 会话归因 —— 透传给 child.run_loop 的 session_id，
        # 经 llm_client 注入 usage_tracker，让子代理的 LLM 消耗落
        # usage_events.session_id（此前恒 NULL，会话级花费统计不含子代理）。
        self._session_id = session_id
        # O1 (2026-09-08): steering 边界投递 —— repo 非 None 且
        # context_task_id 非空时，在 run 启动前与每轮 THINKING 迭代边界，
        # 拉取该任务 pending 的 next_boundary steering 消息注入子代理上下文。
        # 注意 task_id 用 canonical 空间（t1..tN，与 steer 端点/快照一致），
        # 不是 lane 的 "task-<id>" 前缀空间。
        self._context_repo = context_repo
        self._context_task_id = context_task_id

    async def __call__(self, task: Any, agent_id: Optional[str]) -> Dict[str, Any]:
        """Run one subtask via SageAgent.run_loop; return executor-usable dict.

        Args:
            task: orchestration Task（``parameters["goal"]`` 为目标，
                ``parameters["scratch_dir"]`` 为隔离目录）。
            agent_id: 执行 agent 角色。

        Returns:
            ``{"status": "succeeded", "output": <DONE content>}``

        Raises:
            RuntimeError: agent 不存在/已禁用，或子 agent 未产出 DONE content。
        """
        if not agent_id:
            raise RuntimeError("subagent runner 缺少 agent_id")
        if get_enabled_agent(agent_id) is None:
            raise RuntimeError(f"agent {agent_id!r} 不存在或已禁用，无法派发")

        goal = task.parameters.get("goal", "")
        scratch_dir = task.parameters.get("scratch_dir")
        workspace_dir = task.parameters.get("workspace_dir")
        policy_root = workspace_dir or scratch_dir
        policy = ToolPolicy(workspace_root=policy_root) if policy_root else None

        # P2 Task 1 (2026-08-23): 可选 output_schema —— 非 dict 视为未声明。
        schema = task.parameters.get("output_schema")
        if not isinstance(schema, dict):
            schema = None

        child_system = build_system_base()
        profile = get_enabled_agent(agent_id)
        if profile and profile.get("system_prompt"):
            child_system += "\n\n" + profile["system_prompt"]

        user_content = goal
        if schema is not None:
            user_content += _SCHEMA_DIRECTIVE + json.dumps(
                schema, ensure_ascii=False
            )
        # RT9 (round7): 重试带失败上下文 —— executor 在 lane 重试时写入
        # task.parameters["retry_hint"]；缺省（首次执行）无该键，prompt
        # 与旧版逐字一致。
        retry_hint = task.parameters.get("retry_hint")
        if isinstance(retry_hint, dict) and retry_hint.get("last_error"):
            user_content = (
                f"【重试 · 第 {retry_hint.get('attempt', '?')} 次】上次执行失败："
                f"{retry_hint.get('last_error')}\n"
                "请调整方法，避免重蹈覆辙。\n\n" + user_content
            )

        child = SageAgent(agent_id=agent_id, policy=policy)
        # live-events P1: auto 模式注入自动批准包装 enforcer（非危险工具
        # 放行，破坏性/可疑/边界升级仍转人工）。构造失败 → None → 子代理
        # 走默认路径（从 settings 现读，逐次审批）。
        if self._approval_mode == "auto":
            from backend.orchestration.subagent_approval import build_subagent_enforcer

            auto_enforcer = build_subagent_enforcer("auto")
            if auto_enforcer is not None:
                child.permission_enforcer = auto_enforcer
        history = task.parameters.get("history")
        if (
            isinstance(history, list)
            and history
            and all(isinstance(message, dict) for message in history)
        ):
            trimmed = history[1:][-MAX_REPLAY_MESSAGES:]
            messages = [history[0], *trimmed, {"role": "user", "content": user_content}]
        else:
            messages = [
                {"role": "system", "content": child_system},
                {"role": "user", "content": user_content},
            ]
        collected: list[str] = []
        last_error: Optional[str] = None

        # O1: run 启动前投递一次 —— 捕获任务启动前（排队/确认窗口期）
        # 已写入的 pending steering。
        self._deliver_pending_context(messages)

        # O3: session_id 仅在非空且 run_loop 接受时透传 —— 兼容只接受
        # (messages, max_iterations, llm_config) 的测试桩/老调用方。
        run_kwargs: Dict[str, Any] = {"llm_config": self._llm_config}
        if self._session_id and run_loop_accepts_session_id(child):
            run_kwargs["session_id"] = self._session_id

        # P0-3 (2026-08-20): interrupt watcher —— 与 child.run_loop 并发，
        # 取消事件到达即置位子 agent 中断标志；正常结束时 finally 撤销。
        watcher: Optional[asyncio.Task] = None
        if self._interrupt_event is not None:
            async def _watch() -> None:
                await self._interrupt_event.wait()
                child.interrupt()

            watcher = asyncio.create_task(_watch())

        try:
            async for evt in child.run_loop(messages, **run_kwargs):
                # live-events P0: 中间事件投影转发（acting/observing/审批/
                # 提问/failed → 聊天镜像 + canonical task.step.*）。sink
                # 自身吞错（观测绝不杀死执行）；None = 老调用方不转发。
                if self._event_sink is not None:
                    await self._event_sink(evt)
                # O1: THINKING 事件 = 一次 LLM 迭代的边界 —— 在边界拉取
                # pending steering 注入下一轮上下文（messages 就地修改，
                # 下轮 THINKING 前的 LLM 调用自然带上）。
                if (
                    self._context_repo is not None
                    and evt.state.value == "thinking"
                ):
                    self._deliver_pending_context(messages)
                if evt.state.value == "done" and evt.content:
                    collected.append(evt.content)
                elif evt.state.value == "failed" and evt.error:
                    last_error = evt.error
        finally:
            if watcher is not None:
                watcher.cancel()

        if not collected:
            if self._interrupt_event is not None and self._interrupt_event.is_set():
                raise RuntimeError("subtask interrupted by user")
            raise RuntimeError(last_error or "子 agent 未产出 DONE content")

        raw_output = "\n\n".join(collected)
        structured = self._structured_output(raw_output, schema, task)
        return {
            "status": "succeeded",
            "output": structured if structured is not None else raw_output,
            "messages": messages,
        }

    def _deliver_pending_context(self, messages: List[Dict[str, Any]]) -> None:
        """O1 (2026-09-08): 拉取 pending steering 消息注入子代理上下文。

        每条消息以 user role 追加（带来源/类型前缀），随后 mark_delivered
        完成 pending → delivered 生命周期迁移。任何失败只 debug 降级 ——
        steering 是增强能力，绝不因此杀死或阻塞子任务。repo 未接线
        （None）时不做任何事（老调用方/测试零感知）。
        """
        if self._context_repo is None or not self._context_task_id:
            return
        try:
            pending = self._context_repo.list_pending(
                self._context_task_id, apply_mode="next_boundary"
            )
        except Exception as exc:  # noqa: BLE001 — 拉取失败降级
            logger.debug(
                "steering 拉取失败（忽略）task=%s: %s", self._context_task_id, exc
            )
            return
        for message in pending:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"【父代理/用户补充 · {message.message_type}】"
                        f"{message.content_redacted}"
                    ),
                }
            )
            try:
                self._context_repo.mark_delivered(message.context_id)
            except Exception as exc:  # noqa: BLE001 — 迁移失败降级
                logger.debug(
                    "steering mark_delivered 失败（忽略）ctx=%s: %s",
                    message.context_id,
                    exc,
                )
            logger.info(
                "steering 已投递 task=%s ctx=%s type=%s",
                self._context_task_id,
                message.context_id,
                message.message_type,
            )

    @staticmethod
    def _structured_output(
        raw_output: str,
        schema: Optional[Dict[str, Any]],
        task: Any,
    ) -> Optional[str]:
        """schema 声明时提取+校验 JSON；通过返回紧凑 JSON，否则降级原文（None）。

        校验失败只 warning 不 fail —— 结构化是增强而非硬约束，降级保证子任务
        仍产出可用结果（brief Task 1 语义：失败降级原文）。
        """
        if schema is None:
            return None
        payload = extract_json_payload(raw_output)
        if payload is None:
            SubagentRunner._warn_structured_failure(task)
            return None
        try:
            errors = validate_against_schema(payload, schema)
        except Exception as exc:  # noqa: BLE001 — validator 失败必须降级原文
            logger.warning(
                "子任务 %s 结构化输出校验异常，降级原文: %s",
                getattr(task, "task_id", "?"),
                exc,
            )
            return None
        if not errors:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        SubagentRunner._warn_structured_failure(task)
        return None

    @staticmethod
    def _warn_structured_failure(task: Any) -> None:
        """记录结构化输出提取/校验失败，调用方随后保留原文。"""
        logger.warning(
            "子任务 %s 结构化输出校验失败，降级原文",
            getattr(task, "task_id", "?"),
        )


async def run_lane_with_retry(
    executor: LaneExecutor,
    lane: Lane,
    agent_id: Optional[str],
    backoff_secs: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """执行 lane 并在 executor 返回 ``retrying`` 时循环再调（retry 语义）。

    ``LaneExecutor._handle_failure`` 的 retry 分支把 lane 重置为 READY 并返回
    ``{"status": "retrying"}``——重试由调用方**再调 execute_lane 触发**（lane
    调度器模型，非循环内自动重跑）。本 helper 封装该循环；retry_count 累积在
    lane.metadata，max_retries 耗尽后 executor 返回 failed 终态。

    RT10 (round7): ``backoff_secs`` 非空时按 ``RecoveryPolicy.retry_backoff_secs``
    在重试前退避（索引按 retry_count-1 取，越界取末位）——该字段自 2026-08
    声明以来一直无消费者，重试是立即连发。退避计入任务 wall-clock 超时预算
    （O2 的 wait_for 包裹整个 _run_subagent），不会失控。
    """
    result = await executor.execute_lane(lane, agent_id)
    while result.get("status") == "retrying":
        if backoff_secs:
            attempt = result.get("retry_count") or len(backoff_secs)
            try:
                index = max(0, int(attempt) - 1)
            except (TypeError, ValueError):
                index = 0
            delay = backoff_secs[min(index, len(backoff_secs) - 1)]
            if delay > 0:
                logger.info(
                    "lane %s 第 %s 次重试前退避 %ds", lane.lane_id, attempt, delay
                )
                await asyncio.sleep(delay)
        result = await executor.execute_lane(lane, agent_id)
    return result
