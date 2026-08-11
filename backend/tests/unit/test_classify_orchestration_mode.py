"""_classify_orchestration_mode 单元测试 —— tool-toggle 门的判定源。

- force_multi / force_single 短路（跳过 LLM）
- auto：LLM 返回 multi/single 透传
- auto：无 client → single（= 没开编排）
- auto：LLM 异常 → single（降级不阻塞聊天）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.orchestration.chat_dispatcher import _classify_orchestration_mode


def _client_returning(text: str):
    client = MagicMock()
    client.complete = AsyncMock(return_value=text)
    return client


@pytest.mark.asyncio()
async def test_force_multi_short_circuits():
    client = _client_returning("single")  # 即使 LLM 说 single，force 也赢
    assert await _classify_orchestration_mode("hi", "force_multi", client) == "multi"
    client.complete.assert_not_awaited()


@pytest.mark.asyncio()
async def test_force_single_short_circuits():
    client = _client_returning("multi")
    assert await _classify_orchestration_mode("hi", "force_single", client) == "single"
    client.complete.assert_not_awaited()


@pytest.mark.asyncio()
async def test_auto_passes_through_multi():
    client = _client_returning("multi")
    assert (
        await _classify_orchestration_mode("学习量化交易先搜集资料", "auto", client)
        == "multi"
    )


@pytest.mark.asyncio()
async def test_auto_passes_through_single():
    client = _client_returning("single")
    assert await _classify_orchestration_mode("今天天气怎么样", "auto", client) == "single"


@pytest.mark.asyncio()
async def test_auto_no_client_falls_back_single():
    assert await _classify_orchestration_mode("复杂任务", "auto", None) == "single"


@pytest.mark.asyncio()
async def test_auto_llm_error_falls_back_single():
    client = MagicMock()
    client.complete = AsyncMock(side_effect=RuntimeError("llm down"))
    assert await _classify_orchestration_mode("复杂任务", "auto", client) == "single"
