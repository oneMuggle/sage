"""``TaskTranscriptRecorder`` — 子代理过程消息落盘（M1）。

``SubagentRunner`` 消费子 ``run_loop`` 事件时，``SubagentEventSink`` 只把
工具调用/结果投影成"状态事件"（reasoning/content 被显式过滤以降低
token 与 UI 噪声）。本 recorder 与 sink 并行消费同一事件流，把过程以
**消息级**粒度聚合落盘：

- 首个事件 → ``goal`` 行（role=user）
- ``REASONING_DELTA`` / ``CONTENT_DELTA`` 累积，迭代边界（``ACTING`` /
  ``STEP_DONE`` / ``DONE`` / ``FAILED``）flush 成 ``reasoning`` +
  ``assistant`` 行；上游不发 delta 时以整段 ``REASONING`` / ``DONE``
  content 兜底，且不与 delta 重复
- ``ACTING`` → ``tool_call`` 行（参数 JSON），``OBSERVING`` →
  ``tool_result`` 行（结果全文截断、is_error、耗时）
- ``FAILED`` → ``error`` 行

设计约束：recorder 永不抛错（观测绝不能杀死执行）；每任务行数封顶，
超限后静默停止写入；seq 由 repo ``max_seq`` 续接，进程重启后不会
与既有行冲突。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.orch_transcript_repo import (
    OrchTranscriptRepository,
    TaskTranscriptMessage,
)

logger = logging.getLogger(__name__)

#: 每子任务落盘的最大消息行数（防 transcript 无界增长）。
MAX_ROWS_PER_TASK = 2000

#: 聚合后的正文 / 思考行最大字符数。
MAX_TEXT_CHARS = 32_000

#: 工具调用参数 JSON 最大字符数。
MAX_TOOL_ARGS_CHARS = 8_000

#: 工具结果最大字符数。
MAX_TOOL_RESULT_CHARS = 16_000


class TaskTranscriptRecorder:
    """单个子任务的事件 → transcript 行聚合器（``await recorder(evt)``）。"""

    def __init__(
        self,
        *,
        run_id: str,
        task_id: str,
        goal: str,
        agent_id: Optional[str] = None,
        repo: Optional[Any] = None,
    ) -> None:
        self._run_id = run_id
        self._task_id = task_id
        self._goal = goal
        self._agent_id = agent_id
        self._repo_override = repo
        self._default_repo: Optional[OrchTranscriptRepository] = None

        self._seq: Optional[int] = None
        self._rows_written = 0
        self._wrote_goal = False
        self._flushed_text = False

        self._text_buf: List[str] = []
        self._reasoning_buf: List[str] = []
        self._text_len = 0
        self._reasoning_len = 0
        self._saw_reasoning_delta = False
        self._tool_started: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    async def __call__(self, evt: AgentEvent) -> None:
        try:
            self._record(evt)
        except Exception as exc:  # noqa: BLE001 — 观测绝不杀死执行
            logger.debug("transcript 记录失败 task=%s: %s", self._task_id, exc)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _record(self, evt: AgentEvent) -> None:
        if not self._wrote_goal:
            self._wrote_goal = True
            self._append(role="user", message_type="goal", content=self._goal)

        state = evt.state
        if state is AgentState.CONTENT_DELTA and evt.content:
            self._text_len = self._buffer_append(
                self._text_buf, evt.content, self._text_len
            )
        elif state is AgentState.REASONING_DELTA and evt.reasoning:
            self._saw_reasoning_delta = True
            self._reasoning_len = self._buffer_append(
                self._reasoning_buf, evt.reasoning, self._reasoning_len
            )
        elif (
            state is AgentState.REASONING
            and evt.reasoning
            and not self._saw_reasoning_delta
            and not self._reasoning_buf
        ):
            # 上游不发 delta 时以整段 reasoning 兜底；已收到 delta 则不重复。
            self._reasoning_len = self._buffer_append(
                self._reasoning_buf, evt.reasoning, self._reasoning_len
            )
        elif state is AgentState.ACTING and evt.tool_call is not None:
            self._flush_assistant()
            call = evt.tool_call
            self._tool_started[call.id] = time.monotonic()
            self._append(
                role="assistant",
                message_type="tool_call",
                tool_name=call.name,
                tool_call_id=call.id,
                tool_args=self._dump_args(call.arguments),
            )
        elif state is AgentState.OBSERVING and evt.tool_result is not None:
            result = evt.tool_result
            started = self._tool_started.pop(result.tool_call_id, None)
            duration_ms = (
                int((time.monotonic() - started) * 1000) if started is not None else None
            )
            self._append(
                role="tool",
                message_type="tool_result",
                tool_call_id=result.tool_call_id,
                tool_result=(result.content or "")[:MAX_TOOL_RESULT_CHARS],
                is_error=result.is_error,
                duration_ms=duration_ms,
            )
        elif state is AgentState.STEP_DONE:
            self._flush_assistant()
        elif state is AgentState.DONE:
            if self._text_buf or self._reasoning_buf:
                self._flush_assistant()
            elif evt.content and not self._flushed_text:
                # 非流式 provider：没有 delta，直接以终稿兜底。
                self._append(
                    role="assistant",
                    message_type="assistant",
                    content=evt.content[:MAX_TEXT_CHARS],
                )
                self._flushed_text = True
        elif state is AgentState.FAILED and evt.error:
            self._flush_assistant()
            self._append(
                role="assistant",
                message_type="error",
                content=evt.error[:MAX_TEXT_CHARS],
            )

    # ------------------------------------------------------------------
    # 缓冲 / 写入
    # ------------------------------------------------------------------

    @staticmethod
    def _buffer_append(buf: List[str], chunk: str, current_len: int) -> int:
        """追加一段文本，返回新的累计长度（超过上限后不再累积）。"""
        if current_len >= MAX_TEXT_CHARS:
            return current_len
        buf.append(chunk)
        return current_len + len(chunk)

    def _flush_assistant(self) -> None:
        reasoning = "".join(self._reasoning_buf).strip()
        text = "".join(self._text_buf).strip()
        self._reasoning_buf.clear()
        self._text_buf.clear()
        self._reasoning_len = 0
        self._text_len = 0
        self._saw_reasoning_delta = False
        if reasoning:
            self._append(
                role="assistant",
                message_type="reasoning",
                reasoning=reasoning[:MAX_TEXT_CHARS],
            )
        if text:
            self._append(
                role="assistant",
                message_type="assistant",
                content=text[:MAX_TEXT_CHARS],
            )
            self._flushed_text = True

    def _dump_args(self, arguments: Any) -> Optional[str]:
        try:
            dumped = json.dumps(arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            dumped = str(arguments)
        return dumped[:MAX_TOOL_ARGS_CHARS]

    def _repo(self) -> Any:
        if self._repo_override is not None:
            return self._repo_override
        if self._default_repo is None:
            self._default_repo = OrchTranscriptRepository()
        return self._default_repo

    def _append(
        self,
        *,
        role: str,
        message_type: str,
        content: Optional[str] = None,
        reasoning: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tool_args: Optional[str] = None,
        tool_result: Optional[str] = None,
        is_error: bool = False,
        duration_ms: Optional[int] = None,
    ) -> None:
        if self._rows_written >= MAX_ROWS_PER_TASK:
            return
        repo = self._repo()
        if self._seq is None:
            self._seq = repo.max_seq(self._run_id, self._task_id)
        self._seq += 1
        repo.append(
            TaskTranscriptMessage(
                run_id=self._run_id,
                task_id=self._task_id,
                seq=self._seq,
                role=role,
                message_type=message_type,
                content=content,
                reasoning=reasoning,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_args=tool_args,
                tool_result=tool_result,
                is_error=is_error,
                duration_ms=duration_ms,
                created_at=int(time.time() * 1000),
            )
        )
        self._rows_written += 1
