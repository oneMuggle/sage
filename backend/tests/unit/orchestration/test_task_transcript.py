"""TaskTranscriptRecorder —— 子代理 transcript 聚合测试（M1）。

覆盖：
- 首个事件写入 goal 行
- reasoning/content delta 聚合为消息级行（flush 于 STEP_DONE）
- REASONING 整段兜底不与 delta 重复
- tool_call / tool_result 行（参数 JSON、耗时、is_error）
- DONE 不重复写入已 flush 的正文
- FAILED 写 error 行
- repo 异常绝不杀死执行
"""

from __future__ import annotations

import asyncio
import json

from backend.core.legacy.agent_state import (
    AgentEvent,
    AgentState,
    ToolCallRequest,
    ToolCallResult,
)
from backend.data.orch_transcript_repo import TaskTranscriptMessage
from backend.orchestration.transcript import TaskTranscriptRecorder


class FakeRepo:
    def __init__(self) -> None:
        self.rows: list[TaskTranscriptMessage] = []

    def max_seq(self, run_id: str, task_id: str) -> int:
        return self.rows[-1].seq if self.rows else 0

    def append(self, message: TaskTranscriptMessage) -> None:
        self.rows.append(message)


def _ev(state: AgentState, **kwargs) -> AgentEvent:
    return AgentEvent(state=state, **kwargs)


def _recorder(repo) -> TaskTranscriptRecorder:
    return TaskTranscriptRecorder(
        run_id="run-1",
        task_id="t1",
        goal="调研论文",
        agent_id="researcher",
        repo=repo,
    )


def _run(recorder: TaskTranscriptRecorder, *events: AgentEvent) -> None:
    async def _main() -> None:
        for event in events:
            await recorder(event)

    asyncio.run(_main())


def test_first_event_writes_goal_row():
    repo = FakeRepo()
    _run(_recorder(repo), _ev(AgentState.THINKING))

    assert repo.rows[0].message_type == "goal"
    assert repo.rows[0].role == "user"
    assert repo.rows[0].content == "调研论文"
    assert repo.rows[0].seq == 1


def test_reasoning_and_content_deltas_aggregate_and_flush_on_step_done():
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(AgentState.REASONING_DELTA, reasoning="先分析"),
        _ev(AgentState.REASONING_DELTA, reasoning="问题"),
        _ev(AgentState.CONTENT_DELTA, content="结论"),
        _ev(AgentState.CONTENT_DELTA, content="如下"),
        _ev(AgentState.STEP_DONE),
    )

    types = [row.message_type for row in repo.rows]
    assert types == ["goal", "reasoning", "assistant"]
    assert repo.rows[1].reasoning == "先分析问题"
    assert repo.rows[2].content == "结论如下"


def test_full_reasoning_fallback_ignored_when_deltas_seen():
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(AgentState.REASONING_DELTA, reasoning="增量思考"),
        _ev(AgentState.REASONING, reasoning="整段思考-不应重复"),
        _ev(AgentState.STEP_DONE),
    )

    assert [row.message_type for row in repo.rows] == ["goal", "reasoning"]
    assert repo.rows[1].reasoning == "增量思考"


def test_full_reasoning_used_when_no_deltas():
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(AgentState.REASONING, reasoning="整段思考"),
        _ev(AgentState.STEP_DONE),
    )

    assert [row.message_type for row in repo.rows] == ["goal", "reasoning"]
    assert repo.rows[1].reasoning == "整段思考"


def test_tool_call_and_result_rows():
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(
            AgentState.ACTING,
            tool_call=ToolCallRequest(id="call-1", name="web_search", arguments={"q": "sage"}),
        ),
        _ev(
            AgentState.OBSERVING,
            tool_result=ToolCallResult(tool_call_id="call-1", content="结果文本", is_error=False),
        ),
    )

    types = [row.message_type for row in repo.rows]
    assert types == ["goal", "tool_call", "tool_result"]

    call_row = repo.rows[1]
    assert call_row.tool_name == "web_search"
    assert call_row.tool_call_id == "call-1"
    assert json.loads(call_row.tool_args) == {"q": "sage"}

    result_row = repo.rows[2]
    assert result_row.tool_call_id == "call-1"
    assert result_row.tool_result == "结果文本"
    assert result_row.is_error is False
    assert result_row.duration_ms is not None
    assert result_row.duration_ms >= 0


def test_tool_result_error_flag():
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(
            AgentState.ACTING,
            tool_call=ToolCallRequest(id="call-2", name="read_file", arguments={}),
        ),
        _ev(
            AgentState.OBSERVING,
            tool_result=ToolCallResult(tool_call_id="call-2", content="denied", is_error=True),
        ),
    )

    assert repo.rows[-1].is_error is True


def test_tool_call_args_redacts_secret_keys_before_persisting():
    """密钥类参数键在落盘前被替换为 ***（含嵌套），非秘密值保留全文。"""
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(
            AgentState.ACTING,
            tool_call=ToolCallRequest(
                id="call-secret",
                name="http_request",
                arguments={
                    "url": "https://example.test",
                    "api_key": "sk-12345",
                    "headers": {"Authorization": "Bearer tok-9", "Accept": "json"},
                },
            ),
        ),
    )

    call_row = repo.rows[1]
    args = json.loads(call_row.tool_args)
    assert args["url"] == "https://example.test"
    assert args["api_key"] == "***"
    assert args["headers"]["Authorization"] == "***"
    assert args["headers"]["Accept"] == "json"
    assert "sk-12345" not in call_row.tool_args
    assert "tok-9" not in call_row.tool_args


def test_tool_call_args_redacted_even_when_not_json_serializable():
    """json.dumps 失败的字符串化兜底路径同样不落明文密钥。"""
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(
            AgentState.ACTING,
            tool_call=ToolCallRequest(
                id="call-raw",
                name="custom_tool",
                arguments={"auth_token": "tok-raw", "opaque": object()},
            ),
        ),
    )

    call_row = repo.rows[1]
    assert call_row.tool_args is not None
    assert "tok-raw" not in call_row.tool_args
    assert "***" in call_row.tool_args


def test_done_does_not_duplicate_text_flushed_at_step_done():
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(AgentState.CONTENT_DELTA, content="最终答案"),
        _ev(AgentState.STEP_DONE),
        _ev(AgentState.DONE, content="最终答案"),
    )

    assistant_rows = [row for row in repo.rows if row.message_type == "assistant"]
    assert len(assistant_rows) == 1
    assert assistant_rows[0].content == "最终答案"


def test_done_without_deltas_writes_final_content():
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(AgentState.DONE, content="非流式最终答案"),
    )

    assistant_rows = [row for row in repo.rows if row.message_type == "assistant"]
    assert len(assistant_rows) == 1
    assert assistant_rows[0].content == "非流式最终答案"


def test_failed_writes_error_row():
    repo = FakeRepo()
    _run(
        _recorder(repo),
        _ev(AgentState.THINKING),
        _ev(AgentState.FAILED, error="boom"),
    )

    assert [row.message_type for row in repo.rows] == ["goal", "error"]
    assert repo.rows[1].content == "boom"


def test_recorder_swallows_repo_errors():
    class BrokenRepo:
        def max_seq(self, run_id: str, task_id: str) -> int:
            raise RuntimeError("db down")

        def append(self, message: TaskTranscriptMessage) -> None:
            raise RuntimeError("db down")

    async def _main() -> None:
        await _recorder(BrokenRepo())(_ev(AgentState.THINKING))

    asyncio.run(_main())  # 不抛错
