"""_classify_orchestration_mode 单元测试 —— tool-toggle 门的判定源。

- force_multi / force_single 短路（跳过 LLM）
- auto：LLM 返回 multi/single 透传
- auto：无 client → single（= 没开编排）
- auto：LLM 异常 → single（降级不阻塞聊天）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
    # 固定回退客户端为 None，避免测试环境真的存在端点而发起网络请求。
    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        new=lambda: None,
    ):
        assert await _classify_orchestration_mode("复杂任务", "auto", client) == "single"


@pytest.mark.asyncio()
async def test_auto_llm_error_falls_back_to_plain_client():
    """utility 客户端失败 → 回退普通客户端成功 → 得到正常判定而非降级。"""
    bad_client = MagicMock()
    bad_client.complete = AsyncMock(side_effect=RuntimeError("thinking unsupported"))
    good_client = _client_returning("multi")

    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        new=lambda: good_client,
    ):
        result = await _classify_orchestration_mode("复杂任务", "auto", bad_client)

    assert result == "multi"
    bad_client.complete.assert_awaited_once()
    good_client.complete.assert_awaited_once()


@pytest.mark.asyncio()
async def test_auto_handles_braces_in_user_message():
    """回归测试：用户消息含字面量 { / } 时不应触发 .format() KeyError。

    此前 _CLASSIFY_PROMPT.format(message=...) 会对 JSON/代码片段里的
    ``{``/``}`` 抛 KeyError → 静默降级 single + 误导性 "判定失败" 日志。
    现改用 str.replace,带大括号的复杂任务应正常返回 multi。
    """
    client = _client_returning("multi")
    msg = 'complex task {with braces} and JSON {"key": "value"}'
    assert await _classify_orchestration_mode(msg, "auto", client) == "multi"
    client.complete.assert_awaited_once()
    # 验证 prompt 中确实把整段消息原样替换进去了,没有被当成 format 占位符
    sent_prompt = client.complete.await_args.args[0]
    assert msg in sent_prompt
    assert "{message}" not in sent_prompt
