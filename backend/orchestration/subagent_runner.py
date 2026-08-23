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
from typing import Any, Dict, Optional

from backend.agents.profiles import build_system_base, get_enabled_agent
from backend.core.legacy.agent import SageAgent
from backend.domain.tool_policy import ToolPolicy
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.models import Lane
from backend.tools.structured_output_tool import validate_against_schema

logger = logging.getLogger(__name__)

#: schema 声明时注入 user message 的硬性格式要求前缀。
_SCHEMA_DIRECTIVE = (
    "\n\n输出格式硬性要求：你的最终回复必须只包含一个符合以下 JSON Schema "
    "的 JSON 对象（可放在代码围栏中），不要输出其他文字。\n"
)


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
    ) -> None:
        self._llm_config = llm_config
        # P0-3 (2026-08-20): 取消事件 —— ChatDispatcher._cancelled 传入，
        # 置位后 watcher 调 child.interrupt()，子 run_loop 在下轮迭代顶部
        # 发 FAILED 终止（P0-1 通道）。
        self._interrupt_event = interrupt_event

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
        policy = ToolPolicy(workspace_root=scratch_dir) if scratch_dir else None

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

        child = SageAgent(agent_id=agent_id, policy=policy)
        messages = [
            {"role": "system", "content": child_system},
            {"role": "user", "content": user_content},
        ]
        collected: list[str] = []
        last_error: Optional[str] = None

        # P0-3 (2026-08-20): interrupt watcher —— 与 child.run_loop 并发，
        # 取消事件到达即置位子 agent 中断标志；正常结束时 finally 撤销。
        watcher: Optional[asyncio.Task] = None
        if self._interrupt_event is not None:
            async def _watch() -> None:
                await self._interrupt_event.wait()
                child.interrupt()

            watcher = asyncio.create_task(_watch())

        try:
            async for evt in child.run_loop(messages, llm_config=self._llm_config):
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
) -> Dict[str, Any]:
    """执行 lane 并在 executor 返回 ``retrying`` 时循环再调（retry 语义）。

    ``LaneExecutor._handle_failure`` 的 retry 分支把 lane 重置为 READY 并返回
    ``{"status": "retrying"}``——重试由调用方**再调 execute_lane 触发**（lane
    调度器模型，非循环内自动重跑）。本 helper 封装该循环；retry_count 累积在
    lane.metadata，max_retries 耗尽后 executor 返回 failed 终态。
    """
    result = await executor.execute_lane(lane, agent_id)
    while result.get("status") == "retrying":
        result = await executor.execute_lane(lane, agent_id)
    return result
