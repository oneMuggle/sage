# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LLM 流录制 / 回放测试（DSH 对标 R8，B3）。

覆盖：录制 tee（原事件透传 + NDJSON 落盘）、回放按序还原（含
tool_calls 往返）、error 行原位重现失败、目录为空抛 LLMError、
LLMClient.chat_stream_events 三态切换（replay / record / 旁路）。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from backend.core.errors import LLMError
from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse, LLMToolCall
from backend.core.legacy.llm_record_replay import (
    record_stream_events,
    replay_stream_events,
)

pytestmark = pytest.mark.unit


def _sample_events():
    resp = LLMResponse(
        content="答案",
        model="test-model",
        finish_reason="tool_calls",
        tool_calls=[LLMToolCall(id="t1", name="bash", arguments='{"cmd": "ls"}')],
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
    )
    return [
        ("content_delta", "你好"),
        ("reasoning_delta", "思考中"),
        ("content_delta", "，答案是"),
        ("response", resp),
    ]


async def _drain(gen):
    return [item async for item in gen]


class TestRecordReplay:
    def test_record_tees_events_and_writes_ndjson(self, tmp_path):
        events = _sample_events()

        async def _source():
            for e in events:
                yield e

        recorded = asyncio.get_event_loop().run_until_complete(
            _drain(record_stream_events(str(tmp_path), _source()))
        )
        assert recorded == events  # 原事件原样透传

        files = sorted(tmp_path.iterdir())
        assert len(files) == 1
        lines = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
        assert [line["kind"] for line in lines] == [
            "content_delta",
            "reasoning_delta",
            "content_delta",
            "response",
        ]
        # response 行可还原出相同 LLMResponse
        resp_line = lines[-1]["response"]
        assert resp_line["content"] == "答案"
        assert resp_line["tool_calls"][0]["name"] == "bash"

    def test_replay_restores_events_in_order(self, tmp_path):
        async def _source():
            for e in _sample_events():
                yield e

        asyncio.get_event_loop().run_until_complete(
            _drain(record_stream_events(str(tmp_path), _source()))
        )
        replayed = asyncio.get_event_loop().run_until_complete(
            _drain(replay_stream_events(str(tmp_path)))
        )
        assert replayed == _sample_events()
        # tool_calls 是 LLMToolCall 对象（非 dict）
        resp = replayed[-1][1]
        assert isinstance(resp.tool_calls[0], LLMToolCall)

    def test_replay_error_line_raises_in_place(self, tmp_path):
        (tmp_path / "rec_0000.jsonl").write_text(
            json.dumps({"kind": "content_delta", "text": "部分输出"}, ensure_ascii=False)
            + "\n"
            + json.dumps({"kind": "error", "message": "上游 500"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

        async def _run():
            try:
                await _drain(replay_stream_events(str(tmp_path)))
                return None
            except LLMError as exc:
                return exc

        exc = asyncio.get_event_loop().run_until_complete(_run())
        assert exc is not None
        assert "上游 500" in str(exc)

    def test_replay_empty_dir_raises(self, tmp_path):
        with pytest.raises(LLMError):
            asyncio.get_event_loop().run_until_complete(
                _drain(replay_stream_events(str(tmp_path)))
            )

    def test_record_appends_new_file_per_session(self, tmp_path):
        async def _source():
            yield ("content_delta", "x")

        for _ in range(2):
            asyncio.get_event_loop().run_until_complete(
                _drain(record_stream_events(str(tmp_path), _source()))
            )
        assert len(list(tmp_path.iterdir())) == 2


class TestClientThreeModes:
    def _client(self):
        return LLMClient(LLMConfig(api_key="k", base_url="http://x", model="m"))

    def test_replay_mode_bypasses_network(self, tmp_path, monkeypatch):
        async def _source():
            for e in _sample_events():
                yield e

        asyncio.get_event_loop().run_until_complete(
            _drain(record_stream_events(str(tmp_path), _source()))
        )
        monkeypatch.setenv("SAGE_LLM_REPLAY_DIR", str(tmp_path))
        monkeypatch.delenv("SAGE_LLM_RECORD_DIR", raising=False)

        client = self._client()
        # 联网路径若被触碰会炸（client.stream 未配置）——回放完全不触网
        events = asyncio.get_event_loop().run_until_complete(
            _drain(client.chat_stream_events([{"role": "user", "content": "q"}]))
        )
        assert events == _sample_events()

    def test_record_mode_tees_raw_stream(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SAGE_LLM_RECORD_DIR", str(tmp_path))
        monkeypatch.delenv("SAGE_LLM_REPLAY_DIR", raising=False)

        client = self._client()
        raw_events = _sample_events()

        async def _fake_raw(messages, tools=None, tool_choice=None):
            for e in raw_events:
                yield e

        with patch.object(
            client, "_chat_stream_events_raw", side_effect=_fake_raw
        ):
            events = asyncio.get_event_loop().run_until_complete(
                _drain(client.chat_stream_events([{"role": "user", "content": "q"}]))
            )
        assert events == raw_events
        assert len(list(tmp_path.iterdir())) == 1

    def test_bypass_mode_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SAGE_LLM_REPLAY_DIR", raising=False)
        monkeypatch.delenv("SAGE_LLM_RECORD_DIR", raising=False)

        client = self._client()
        raw_events = [("content_delta", "直通")]

        async def _fake_raw(messages, tools=None, tool_choice=None):
            for e in raw_events:
                yield e

        with patch.object(
            client, "_chat_stream_events_raw", side_effect=_fake_raw
        ) as fake:
            events = asyncio.get_event_loop().run_until_complete(
                _drain(client.chat_stream_events([{"role": "user", "content": "q"}]))
            )
        assert events == raw_events
        # 旁路模式直接消费 raw 生成器，不经录制模块
        fake.assert_called_once_with(
            [{"role": "user", "content": "q"}], None, None
        )
        assert list(tmp_path.iterdir()) == []
