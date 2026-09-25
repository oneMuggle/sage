# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""录制 → 回放 → 事件日志 → 投影 全链路确定性测试（DSH 对标 R12，B3b）。

把 R8（录制/回放）与 SE1/SE2（事件日志 + 投影 + 读取切换）串联：
**一段录制的 LLM 事件流，重放两次产出的请求装配逐字节一致**，且经事件
日志投影后与表投影 parity——这是"离线复现真实会话"的地基（dsh
snapshot 回放测试同款输入形态）。

纯确定性：不联网、不依赖真实 LLM、时钟冻结在合成值。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from backend.chat.event_projection import events_to_history
from backend.chat.history_context import build_request_messages_from_events
from backend.core.legacy.llm_client import (
    LLMClient,
    LLMConfig,
    LLMResponse,
    LLMToolCall,
)
from backend.core.legacy.llm_record_replay import (
    record_stream_events,
    replay_stream_events,
)
from backend.data.session_event_repo import SessionEventRepository
from backend.data.session_repo import Message, MessageRepository
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


def _scripted_events():
    """一段脚本化的 LLM 事件流（含工具调用）。"""
    resp = LLMResponse(
        content="已列出目录内容",
        model="offline-model",
        finish_reason="tool_calls",
        tool_calls=[LLMToolCall(id="t1", name="list_dir", arguments='{"path": "."}')],
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
    )
    return [
        ("content_delta", "让我看一下目录"),
        ("reasoning_delta", "用户想列目录"),
        ("content_delta", "。"),
        ("response", resp),
    ]


def test_record_replay_deterministic(tmp_path):
    """同一录制重放两次：产出的事件流逐字节一致（确定性契约）。"""
    asyncio.get_event_loop().run_until_complete(
        _drain(record_stream_events(str(tmp_path), _iter_events(_scripted_events())))
    )
    first = asyncio.get_event_loop().run_until_complete(
        _drain(replay_stream_events(str(tmp_path)))
    )
    second = asyncio.get_event_loop().run_until_complete(
        _drain(replay_stream_events(str(tmp_path)))
    )
    assert first == _scripted_events()
    assert second == _scripted_events()


async def _iter_events(events):
    for e in events:
        yield e


async def _drain(gen):
    return [item async for item in gen]


def test_recorded_replay_feeds_request_assembly(tmp_path):
    """回放产物（response.content）作为用户可见历史 → 装配请求成功。"""
    asyncio.get_event_loop().run_until_complete(
        _drain(record_stream_events(str(tmp_path), _iter_events(_scripted_events())))
    )
    replayed = asyncio.get_event_loop().run_until_complete(
        _drain(replay_stream_events(str(tmp_path)))
    )
    responses = [p for k, p in replayed if k == "response"]
    assert len(responses) == 1
    assert responses[0].content == "已列出目录内容"

    # 以回放内容组装请求（模拟下一轮对话把上轮结果纳入历史）
    messages, omitted = build_request_messages_from_events(
        system_content="系统",
        user_text="继续",
        events=[
            {
                "type": "message.appended",
                "payload": {
                    "id": "m1",
                    "role": "assistant",
                    "content": responses[0].content,
                    "subtype": None,
                    "segment_id": 0,
                    "tool_calls": None,
                    "created_at": 1,
                },
            }
        ],
        budget_tokens=5000,
    )
    assert omitted == 0
    assert messages[-2] == {"role": "assistant", "content": "已列出目录内容"}
    assert messages[-1] == {"role": "user", "content": "继续"}


def test_recorded_events_drive_event_log_projection(setup_test_db, tmp_path):
    """录制 → 回放 → 写入事件日志（模拟运行期双写）→ 投影 parity。"""
    sid = "s-replay-e2e"
    ensure_session(setup_test_db, sid)
    asyncio.get_event_loop().run_until_complete(
        _drain(record_stream_events(str(tmp_path), _iter_events(_scripted_events())))
    )
    replayed = asyncio.get_event_loop().run_until_complete(
        _drain(replay_stream_events(str(tmp_path)))
    )

    # 模拟运行期：回放的内容增量聚合成 assistant 消息，经 save() 双写
    deltas = "".join(p for k, p in replayed if k == "content_delta")
    repo = MessageRepository()
    repo.save(
        Message(
            id="replay-msg-1",
            session_id=sid,
            role="assistant",
            content=deltas,
            created_at=1700000000000,
        )
    )

    events = SessionEventRepository().get_by_session(sid)
    history = events_to_history(events)
    assert history == [{"role": "assistant", "content": "让我看一下目录。"}]


def test_record_replay_client_interceptor_roundtrip(tmp_path, monkeypatch):
    """client 拦截器录制后，同 client 在 replay 模式下产出一致事件。"""
    monkeypatch.setenv("SAGE_LLM_RECORD_DIR", str(tmp_path))
    monkeypatch.delenv("SAGE_LLM_REPLAY_DIR", raising=False)
    client = LLMClient(LLMConfig(api_key="k", base_url="http://x", model="m"))

    async def _fake_raw(messages, tools=None, tool_choice=None):
        for e in _scripted_events():
            yield e

    with patch.object(
        client, "_chat_stream_events_raw", side_effect=_fake_raw
    ):
        recorded = asyncio.get_event_loop().run_until_complete(
            _drain(client.chat_stream_events([{"role": "user", "content": "q"}]))
        )
    assert recorded == _scripted_events()

    monkeypatch.setenv("SAGE_LLM_REPLAY_DIR", str(tmp_path))
    monkeypatch.delenv("SAGE_LLM_RECORD_DIR", raising=False)
    replayed = asyncio.get_event_loop().run_until_complete(
        _drain(client.chat_stream_events([{"role": "user", "content": "q"}]))
    )
    assert replayed == _scripted_events()


def test_record_file_is_valid_ndjson(tmp_path):
    """录制文件每行都是合法 JSON（NDJSON 契约，供外部工具消费）。"""
    asyncio.get_event_loop().run_until_complete(
        _drain(record_stream_events(str(tmp_path), _iter_events(_scripted_events())))
    )
    f = next(tmp_path.iterdir())
    for line in f.read_text(encoding="utf-8").splitlines():
        assert isinstance(json.loads(line), dict)


