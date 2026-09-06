"""``SubagentEventSink`` — 子代理内部事件的投影转发器（live-events P0）。

背景：``SubagentRunner`` 消费子 ``run_loop`` 时原本只收集 done/failed，
中间事件（工具调用/结果/审批）全部丢弃 —— 用户只能被动等待任务级
task_status 迁移，点开 Drawer 也没有子代理内部事件（task.step.* 协议
有定义无生产者）。本模块把子 run_loop 事件**投影**到既有双通道：

- 聊天流（``entry_queue``）：轻量镜像 ``subagent_event`` 事件，供任务树
  行内实时步骤 / 聊天内联面板渲染；审批请求另发一条带子代理上下文的
  ``permission_request`` 镜像（修复审批黑洞）。
- canonical RunEvent 流（``EventHub``）：``task.step.started/completed/failed``
  与 ``task.approval_requested``，供 Drawer 的 EventTimeline、快照
  （snapshot_store 已消费 task.step.*）与 observe_subagents 消费。

设计约束：
- **投影而非全量转发** —— 子代理 reasoning/content 不转发（token 与 UI
  双重噪声）；结果只带截断预览；每子任务事件预算封顶（防事件洪流），
  超预算后静默丢弃（审批/提问转发不受预算限制 —— 安全通道不能被挤掉）。
- sink 永不抛错：任何异常降级为 debug 日志（观测绝不能杀死执行）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.domain.orch_events import ControlEventType, RunEvent, StepEventType, make_event
from backend.services.permission_gate import summarize_tool_args

logger = logging.getLogger(__name__)

#: 每子任务转发的最大事件数（防事件洪流）。审批/提问转发不受此限制。
MAX_EVENTS_PER_SUBTASK = 200

#: 工具结果预览截断长度（聊天镜像）。
MAX_RESULT_PREVIEW_CHARS = 200

#: canonical step 事件 payload 里的结果预览截断长度。
MAX_STEP_PREVIEW_CHARS = 500

#: 任务树行内 live 步骤文案截断长度。
MAX_LIVE_LINE_CHARS = 120

#: 子代理事件阶段（聊天镜像 ``phase`` 字段取值）
PHASE_TOOL_CALL = "tool_call"
PHASE_TOOL_RESULT = "tool_result"
PHASE_APPROVAL_REQUESTED = "approval_requested"
PHASE_APPROVAL_RESOLVED = "approval_resolved"
PHASE_QUESTION = "question"
PHASE_FAILED = "failed"


class SubagentEventSink:
    """单个子任务的异步事件投影器（``await sink(evt: AgentEvent)``）。

    由 ``ChatDispatcher._run_subagent_impl`` 每子任务构造一次，注入
    ``SubagentRunner``；后者在消费子 run_loop 时逐事件 await 本对象。

    Args:
        emit_chat: 聊天流入队回调（dispatcher 提供，内部 put_nowait + 降级）。
        publish_event: canonical RunEvent 发布回调（EventHub.publish 或
            ``None`` = canonical 通道未装配，仅镜像聊天流）。
        note_approval: 审批请求登记回调（request_id → dispatcher 待决表），
            供 ``/permissions/{id}/answer`` 路由回填 resolved 事件。
    """

    def __init__(
        self,
        *,
        run_id: str,
        task_id: str,
        entity_task_id: str,
        agent_id: str,
        goal: str,
        parent_tool_call_id: Optional[str] = None,
        emit_chat: Callable[[Dict[str, Any]], None],
        publish_event: Optional[Callable[[RunEvent], Awaitable[None]]] = None,
        note_approval: Optional[Callable[[str], None]] = None,
        max_events: int = MAX_EVENTS_PER_SUBTASK,
    ) -> None:
        self._run_id = run_id
        self._task_id = task_id
        self._entity_task_id = entity_task_id
        self._agent_id = agent_id
        self._goal = goal
        self._parent_tool_call_id = parent_tool_call_id
        self._emit_chat = emit_chat
        self._publish_event = publish_event
        self._note_approval = note_approval
        self._budget = max_events
        # tool_call_id → {"name", "started"}：observing 时算 duration
        self._in_flight: Dict[str, Dict[str, Any]] = {}

    async def __call__(self, evt: AgentEvent) -> None:
        try:
            await self._project(evt)
        except Exception as exc:  # noqa: BLE001 — 观测绝不杀死执行
            logger.debug("subagent 事件投影失败 task=%s: %s", self._task_id, exc)

    # ------------------------------------------------------------------
    # 投影主路径
    # ------------------------------------------------------------------

    async def _project(self, evt: AgentEvent) -> None:
        state = evt.state
        if state is AgentState.ACTING and evt.tool_call is not None:
            await self._on_tool_call(evt)
        elif state is AgentState.OBSERVING and evt.tool_result is not None:
            await self._on_tool_result(evt)
        elif state is AgentState.PERMISSION_REQUEST and evt.permission_request:
            await self._on_permission_request(evt)
        elif state is AgentState.ASK_USER_QUESTION and evt.user_question:
            await self._on_question(evt)
        elif state is AgentState.FAILED:
            await self._on_failed(evt)
        # THINKING / REASONING / CONTENT_DELTA / DONE：不转发（降噪）。

    # -- 工具调用开始 --------------------------------------------------

    async def _on_tool_call(self, evt: AgentEvent) -> None:
        tc = evt.tool_call
        assert tc is not None
        args_summary = summarize_tool_args(tc.arguments)
        self._in_flight[tc.id] = {"name": tc.name, "started": time.monotonic()}
        self._emit_mirror(self._mirror(
            phase=PHASE_TOOL_CALL,
            iteration=evt.iteration,
            tool_name=tc.name,
            args_summary=args_summary,
            live_step=_live_line(tc.name, args_summary),
        ))
        await self._publish(
            StepEventType.STEP_STARTED.value,
            _entity_step(self._entity_task_id, self._agent_id,
                         step_id=f"tool-{tc.id}", name=tc.name),
            {
                "step_id": f"tool-{tc.id}",
                "step_name": tc.name,
                "kind": "tool_call",
                "args_summary": args_summary,
                "iteration": evt.iteration,
            },
        )

    # -- 工具结果 ------------------------------------------------------

    async def _on_tool_result(self, evt: AgentEvent) -> None:
        tr = evt.tool_result
        assert tr is not None
        meta = self._in_flight.pop(tr.tool_call_id, None)
        tool_name = (meta or {}).get("name")
        duration_ms = None
        if meta is not None:
            duration_ms = int((time.monotonic() - meta["started"]) * 1000)
        preview = (tr.content or "")[:MAX_RESULT_PREVIEW_CHARS]
        self._emit_mirror(self._mirror(
            phase=PHASE_TOOL_RESULT,
            iteration=evt.iteration,
            tool_name=tool_name,
            preview=preview,
            is_error=tr.is_error,
            live_step=_live_line(tool_name or "tool",
                                 preview or ("错误" if tr.is_error else "完成")),
        ))
        await self._publish(
            StepEventType.STEP_FAILED.value if tr.is_error
            else StepEventType.STEP_COMPLETED.value,
            _entity_step(self._entity_task_id, self._agent_id,
                         step_id=f"tool-{tr.tool_call_id}", name=tool_name),
            {
                "step_id": f"tool-{tr.tool_call_id}",
                "step_name": tool_name,
                "preview": (tr.content or "")[:MAX_STEP_PREVIEW_CHARS],
                "is_error": tr.is_error,
                "duration_ms": duration_ms,
            },
        )

    # -- 审批请求（修复审批黑洞） ---------------------------------------

    async def _on_permission_request(self, evt: AgentEvent) -> None:
        req = evt.permission_request or {}
        request_id = str(req.get("request_id", ""))
        # 审批镜像不受事件预算限制 —— 安全通道不能被挤掉。
        self._emit_chat({
            "state": "permission_request",
            "iteration": evt.iteration,
            "agent_id": self._agent_id,
            "permission_request": {
                **req,
                "subagent": self._subagent_ctx(),
            },
        })
        self._emit_mirror(self._mirror(
            phase=PHASE_APPROVAL_REQUESTED,
            iteration=evt.iteration,
            tool_name=req.get("tool_name"),
            live_step=f"⏳ 等待审批: {req.get('tool_name', 'tool')}",
        ))
        if request_id and self._note_approval is not None:
            self._note_approval(request_id)
        await self._publish(
            ControlEventType.TASK_APPROVAL_REQUESTED.value,
            _entity_step(self._entity_task_id, self._agent_id),
            {
                "request_id": request_id,
                "tool_name": req.get("tool_name"),
                "risk": req.get("risk"),
                "message": req.get("message"),
            },
        )
        # 任务态投影：快照/reducer 的 waiting_approval 徽章（resolver 以
        # task.started 恢复 running）。
        await self._publish(
            "task.waiting_approval",
            _entity_step(self._entity_task_id, self._agent_id),
            {"reason": "awaiting_subagent_approval", "request_id": request_id},
        )

    # -- 子代理提问 ----------------------------------------------------

    async def _on_question(self, evt: AgentEvent) -> None:
        question = evt.user_question or {}
        self._emit_chat({
            "state": "ask_user_question",
            "iteration": evt.iteration,
            "agent_id": self._agent_id,
            "user_question": {
                **question,
                "subagent": self._subagent_ctx(),
            },
        })
        self._emit_mirror(self._mirror(
            phase=PHASE_QUESTION,
            iteration=evt.iteration,
            live_step=f"❓ 向用户提问: {str(question.get('question', ''))[:80]}",
        ))

    # -- 失败 ----------------------------------------------------------

    async def _on_failed(self, evt: AgentEvent) -> None:
        error = evt.error or "unknown error"
        self._emit_mirror(self._mirror(
            phase=PHASE_FAILED,
            iteration=evt.iteration,
            preview=error[:MAX_RESULT_PREVIEW_CHARS],
            is_error=True,
            live_step=f"✗ 失败: {error[:80]}",
        ))
        await self._publish(
            StepEventType.STEP_FAILED.value,
            _entity_step(self._entity_task_id, self._agent_id),
            {"error": error[:MAX_STEP_PREVIEW_CHARS]},
        )

    # -- 审批解决（由 dispatcher.resolve_approval 复用） ----------------

    async def emit_approval_resolved(self, request_id: str, approved: bool) -> None:
        self._emit_mirror(self._mirror(
            phase=PHASE_APPROVAL_RESOLVED,
            tool_name=None,
            live_step=("✓ 已批准，继续执行" if approved else "✗ 已拒绝"),
            approved=approved,
        ))
        await self._publish(
            ControlEventType.TASK_APPROVAL_RESOLVED.value,
            _entity_step(self._entity_task_id, self._agent_id),
            {"request_id": request_id, "approved": approved},
        )
        if approved:
            await self._publish(
                "task.started",
                _entity_step(self._entity_task_id, self._agent_id),
                {"resumed_from": "waiting_approval"},
            )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _emit_mirror(self, event: Optional[Dict[str, Any]]) -> None:
        """镜像入队前的统一防御：预算耗尽时 _mirror 返回 None,不外发。"""
        if event is not None:
            self._emit_chat(event)

    def _mirror(self, *, phase: str, iteration: int = 0, live_step: str = "",
                tool_name: Optional[str] = None, args_summary: Optional[str] = None,
                preview: Optional[str] = None, is_error: bool = False,
                approved: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        """构造聊天流 ``subagent_event`` 镜像；预算耗尽返回 None（丢弃）。"""
        if self._budget <= 0:
            return None
        self._budget -= 1
        event: Dict[str, Any] = {
            "state": "subagent_event",
            "run_id": self._run_id,
            "task_id": self._task_id,
            "agent_id": self._agent_id,
            "goal": self._goal,
            "parent_tool_call_id": self._parent_tool_call_id,
            "phase": phase,
            "iteration": iteration,
            "live_step": live_step,
            "ts": int(time.time() * 1000),
        }
        if tool_name is not None:
            event["tool_name"] = tool_name
        if args_summary is not None:
            event["args_summary"] = args_summary
        if preview is not None:
            event["preview"] = preview
        if is_error:
            event["is_error"] = True
        if approved is not None:
            event["approved"] = approved
        return event

    def _subagent_ctx(self) -> Dict[str, Any]:
        return {
            "run_id": self._run_id,
            "task_id": self._task_id,
            "agent_id": self._agent_id,
            "goal": self._goal,
        }

    async def _publish(self, event_type: str, entity: Dict[str, Any],
                       payload: Dict[str, Any]) -> None:
        """canonical 事件发布；未装配/失败全吞降级（时间线尽力而为）。"""
        if self._publish_event is None:
            return
        event = make_event(
            run_id=self._run_id,
            seq=0,  # EventHub 统一分配 run 内单调 seq
            event_type=event_type,
            producer="subagent-runner",
            entity=entity,
            payload=payload,
        )
        try:
            await self._publish_event(event)
        except Exception as exc:  # noqa: BLE001 — 观测尽力而为
            logger.debug("canonical 事件发布失败 task=%s: %s", self._task_id, exc)


def _entity_step(lane_task_id: str, agent_id: str,
                 step_id: Optional[str] = None,
                 name: Optional[str] = None) -> Dict[str, Any]:
    """构造 canonical 事件 entity（task_id 用 lane 层 ``task-<id>`` 键）。"""
    entity: Dict[str, Any] = {"task_id": lane_task_id, "agent_id": agent_id}
    if step_id is not None:
        entity["step_id"] = step_id
    if name is not None:
        entity["step_name"] = name
    return entity


def _live_line(tool_name: str, detail: str) -> str:
    """任务树行内实时步骤文案（截断防刷屏）。"""
    line = f"🔧 {tool_name} {detail}".strip()
    return line[:MAX_LIVE_LINE_CHARS]


__all__ = [
    "SubagentEventSink",
    "MAX_EVENTS_PER_SUBTASK",
    "MAX_RESULT_PREVIEW_CHARS",
    "MAX_STEP_PREVIEW_CHARS",
    "MAX_LIVE_LINE_CHARS",
    "PHASE_TOOL_CALL",
    "PHASE_TOOL_RESULT",
    "PHASE_APPROVAL_REQUESTED",
    "PHASE_APPROVAL_RESOLVED",
    "PHASE_QUESTION",
    "PHASE_FAILED",
]
