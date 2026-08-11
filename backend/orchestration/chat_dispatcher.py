"""ChatDispatcher — 轻量子 agent 执行器（Multi-Agent Orchestration 方案 C）。

conductor（主 LLM）经 ``dispatch_subagents`` 工具调用本 dispatcher，把
``[{agent_id, goal}]`` 并行派发给子 ``SageAgent``。纯内存，单次聊天 run
生命周期内存在，不持久化 —— 与 ``backend/orchestration/`` 的 lane 编排层
互不干扰（不建 lane、不写 lane 表）。

子 agent 用 ``SageAgent(agent_id=...)`` 非 bare 构造：bare=True 会留空
tool_registry（子 agent 需要 profile 白名单工具，如 researcher 的
web_search / writer 的 write_file）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.agents.profiles import build_system_base, get_enabled_agent
from backend.core.legacy.agent import SageAgent

logger = logging.getLogger(__name__)

#: 并发上限 —— 子 agent 同时执行数（多出的排队等待）。
MAX_CONCURRENT_SUBAGENTS = 4

#: 单子结果截断上限 —— 聚合 markdown 进 conductor 上下文，防止灌爆。
MAX_SUBAGENT_RESULT_CHARS = 50 * 1024

#: task_status.output_preview 上限（UI 展开预览）。
MAX_OUTPUT_PREVIEW_CHARS = 500

#: 编排语义判定 prompt（轻量二分类）：LLM 只需回答 multi / single。
_CLASSIFY_PROMPT = """判断以下用户消息是否需要多 agent 协作（拆解为多个子任务、由不同角色并行执行）才能最好地完成。
只需返回一个词：multi 或 single。
- multi：复杂任务、多步骤、需要搜集资料/研究/并行工作。例如"我需要学习量化交易，先搜集相关资料后，整理一份学习资料和操作指南"。
- single：简单问答、单步请求。例如"今天天气怎么样"、"解释什么是递归"。

用户消息: {message}

答案:"""


async def _classify_orchestration_mode(
    message: str,
    orchestration_mode: str,
    llm_client: Optional[Any] = None,
) -> str:
    """语义判定消息是否进编排（multi）还是单 agent（single）。

    - ``force_multi`` / ``force_single``：用户 override，直接定，跳过 LLM
    - ``auto``：轻量 LLM 二分类；无 client / 失败 → ``single``（= 没开编排）

    这是 tool-toggle 门的判定源：mode=single 时 producer 不注册
    dispatch_subagents 工具（简单任务在结构上无法被过度拆解）。
    """
    if orchestration_mode == "force_multi":
        return "multi"
    if orchestration_mode == "force_single":
        return "single"
    if llm_client is None:
        return "single"
    try:
        # str.replace, NOT .format(): user message may contain literal { / }
        # (JSON / code snippets / template strings) which would make .format()
        # raise KeyError/IndexError and silently downgrade to single with a
        # misleading "判定失败" log.
        prompt = _CLASSIFY_PROMPT.replace("{message}", message)
        response = await llm_client.complete(prompt)
        return "multi" if "multi" in (response or "").strip().lower() else "single"
    except Exception as exc:  # noqa: BLE001 — 判定失败必须降级，绝不阻塞聊天
        logger.warning("编排语义判定失败，降级 single: %s", exc)
        return "single"


@dataclass
class ChatTaskState:
    """单个子任务的可变状态（dispatcher 内存态，不落库）。"""

    task_id: str
    agent_id: str
    goal: str
    status: str = "queued"  # queued|running|done|failed
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


class ChatDispatcher:
    """并行执行子任务并向聊天流推送 task_status 事件的轻量调度器。"""

    def __init__(
        self,
        stream_id: str,
        entry_queue: asyncio.Queue[Dict[str, Any]],
        run_id: str,
        llm_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.stream_id = stream_id
        self.entry_queue = entry_queue
        self.run_id = run_id
        self.llm_config = llm_config
        self._states: Dict[str, ChatTaskState] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBAGENTS)

    async def dispatch(self, tasks: List[Dict[str, str]]) -> str:
        """并行执行子任务，返回聚合 markdown（截断后进 conductor 上下文）。

        Args:
            tasks: ``[{"agent_id": ..., "goal": ...}]``。按传入顺序编号
                ``t{index+1}``（与 producer 的 task_plan 契约一致）。

        Returns:
            聚合 markdown：每个子结果截断 MAX_SUBAGENT_RESULT_CHARS 后拼接；
            单任务失败以错误摘要参与聚合，其余任务继续（错误隔离）。
        """
        states: List[ChatTaskState] = []
        for index, raw in enumerate(tasks):
            # 缺 agent_id（malformed input）→ 失败事件占位，不抛穿整次 dispatch。
            # 让 conductor 看到 status=failed + error，能定位 producer bug。
            try:
                state = ChatTaskState(
                    task_id=f"t{index + 1}",
                    agent_id=raw["agent_id"],
                    goal=raw.get("goal", ""),
                )
            except KeyError as exc:
                state = ChatTaskState(
                    task_id=f"t{index + 1}",
                    agent_id="<missing>",
                    goal=raw.get("goal", ""),
                )
                self._states[state.task_id] = state
                states.append(state)
                self._emit_task_status(state)  # queued (status 仍是 "queued")
                state.status = "failed"
                state.error = f"missing required key: {exc.args[0]}"
                self._emit_task_status(state)  # failed
                continue
            self._states[state.task_id] = state
            states.append(state)
            self._emit_task_status(state)  # queued

        async def _run_one(state: ChatTaskState) -> None:
            async with self._semaphore:
                state.status = "running"
                state.started_at = time.time()
                self._emit_task_status(state)
                # 让其他子任务也有机会 emit running,保证 queued/running/done 三阶段序
                await asyncio.sleep(0)
                try:
                    content = await self._run_subagent(state)
                    state.status = "done"
                    state.output = content
                except Exception as exc:  # noqa: BLE001 — 单任务失败隔离
                    state.status = "failed"
                    state.error = str(exc)
                    logger.warning("subagent %s failed: %s", state.task_id, exc)
                finally:
                    state.finished_at = time.time()
                    self._emit_task_status(state)

        await asyncio.gather(*(_run_one(s) for s in states if s.status != "failed"))
        return self._aggregate(states)

    async def _run_subagent(self, state: ChatTaskState) -> str:
        """跑单个子 SageAgent.run_loop，收集 DONE content。"""
        # spec §5.1: agent_id 不合法（不存在/禁用）→ 快速失败，错误进聚合
        # （conductor 可改派/重试），而不是拿 base prompt 跑一个无身份的 child。
        child_profile = get_enabled_agent(state.agent_id)
        if child_profile is None:
            raise RuntimeError(
                f"agent {state.agent_id!r} 不存在或已禁用，无法派发"
            )
        child_system = build_system_base()
        if child_profile.get("system_prompt"):
            child_system += "\n\n" + child_profile["system_prompt"]

        child = SageAgent(agent_id=state.agent_id)
        messages = [
            {"role": "system", "content": child_system},
            {"role": "user", "content": state.goal},
        ]
        collected: List[str] = []
        async for evt in child.run_loop(messages, llm_config=self.llm_config):
            if evt.state.value == "done" and evt.content:
                collected.append(evt.content)
        if not collected:
            raise RuntimeError("子 agent 未产出 DONE content")
        return "\n\n".join(collected)

    def _emit_task_status(self, state: ChatTaskState) -> None:
        """推 task_status 事件；队列满/关闭静默降级（进度尽力而为）。"""
        event: Dict[str, Any] = {
            "state": "task_status",
            "run_id": self.run_id,
            "task_id": state.task_id,
            "status": state.status,
            "agent_id": state.agent_id,
            "goal": state.goal,
            "error": state.error,
            "output_preview": self._preview(state),
        }
        try:
            self.entry_queue.put_nowait(event)
        except Exception:  # noqa: BLE001
            logger.debug("task_status 推送失败（队列满/关闭），忽略")

    def _preview(self, state: ChatTaskState) -> Optional[str]:
        """done → output 前 500 字；failed → error 前 500 字。"""
        if state.status == "done" and state.output:
            return state.output[:MAX_OUTPUT_PREVIEW_CHARS]
        if state.status == "failed" and state.error:
            return state.error[:MAX_OUTPUT_PREVIEW_CHARS]
        return None

    def _aggregate(self, states: List[ChatTaskState]) -> str:
        """聚合 markdown：成功子结果 + 失败摘要，每项截断。"""
        blocks: List[str] = []
        for state in states:
            header = f"## 子任务 {state.task_id}（{state.agent_id}）"
            if state.status == "done" and state.output:
                body = state.output[:MAX_SUBAGENT_RESULT_CHARS]
                blocks.append(f"{header}\n\n{body}")
            elif state.status == "failed":
                err = (state.error or "未知错误")[:MAX_SUBAGENT_RESULT_CHARS]
                blocks.append(f"{header}\n\n[失败] {err}")
            else:
                blocks.append(f"{header}\n\n[状态: {state.status}]")
        return "\n\n".join(blocks)
