"""Reasoning fake streaming 测试。

验证 legacy_routes.py producer 对 reasoning 事件做切块，
输出 reasoning_delta + reasoning_done 事件序列。
"""

import json
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.main import app

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


@pytest.mark.asyncio()
async def test_reasoning_emits_delta_and_done_events():
    """reasoning 事件应被切块为 reasoning_delta + 最终的 reasoning_done。"""
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    # 20 字符的 reasoning，按 6 字符切块 → 4 个 delta (6+6+6+2) + 1 个 done
    reasoning_text = "A" * 20

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.REASONING,
            iteration=0,
            reasoning=reasoning_text,
        )
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=0,
            content="回答",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. create
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "测试 reasoning 流式",
                },
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            # 2. attach — 获取 NDJSON 流
            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200
            assert attach_resp.headers["content-type"].startswith("application/x-ndjson")

            events = _parse_ndjson(attach_resp.text)

    # 验证事件序列
    reasoning_deltas = [e for e in events if e["state"] == "reasoning_delta"]
    reasoning_dones = [e for e in events if e["state"] == "reasoning_done"]

    # 应有至少 1 个 delta 和 1 个 done
    assert len(reasoning_deltas) >= 1, (
        f"无 reasoning_delta 事件，事件序列: {[e['state'] for e in events]}"
    )
    assert len(reasoning_dones) == 1, f"应有 1 个 reasoning_done，实际: {len(reasoning_dones)}"

    # 所有 delta 的 reasoning 拼接应等于完整 reasoning
    accumulated = "".join(e["reasoning"] for e in reasoning_deltas)
    assert accumulated == reasoning_text, f"delta 拼接 '{accumulated}' != 完整 '{reasoning_text}'"

    # reasoning_done 应携带完整 reasoning
    assert reasoning_dones[0]["reasoning"] == reasoning_text

    # 事件顺序：第一个事件是 thinking，所有 reasoning_delta 在 reasoning_done 之前
    assert events[0]["state"] == "thinking"
    delta_indices = [i for i, e in enumerate(events) if e["state"] == "reasoning_delta"]
    done_indices = [i for i, e in enumerate(events) if e["state"] == "reasoning_done"]
    assert max(delta_indices) < min(done_indices), "reasoning_delta 应在 reasoning_done 之前"

    # DONE 事件应在最后
    assert events[-1]["state"] == "done"
