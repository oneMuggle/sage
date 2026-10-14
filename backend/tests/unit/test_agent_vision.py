"""Vision model fallback unit tests.

Task 2 评审要求（MEDIUM-2）：原测试把 ``_get_model_capabilities`` 与
``_inject_images_as_content`` 全部 mock 掉，断言的其实是 fixture 自己的
return_value，真正跑到的只有路由的两行，edge case 最多的
``_inject_images_as_content`` 零覆盖。故下面绝大多数用例直接调用真实
方法（用 ``SageAgent.__new__`` 绕开 __init__ 的记忆栈 / LLM 客户端开销）。
"""

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.llm_client import LLMConfig

PNG_URL = "data:image/png;base64,AAAA"
JPEG_URL = "data:image/jpeg;base64,BBBB"


def _bare_agent(model: str = "gpt-4o", provider: str = "openai") -> SageAgent:
    """构造一个只带 llm_config 的轻量 agent（跳过 __init__ 的重型装配）。"""
    agent = SageAgent.__new__(SageAgent)
    agent.llm_config = LLMConfig(model=model, provider=provider)
    return agent


class TestInjectImagesAsContent:
    """``_inject_images_as_content`` 的真实行为（直接调，不用 mock）。"""

    def test_injects_single_image_into_last_user_message(self):
        agent = _bare_agent()
        messages = [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "描述这张图片"},
        ]

        result = agent._inject_images_as_content(messages, [PNG_URL])

        assert len(result) == 2
        # system 消息原样保留
        assert result[0] == {"role": "system", "content": "系统提示"}
        assert result[1]["role"] == "user"
        content = result[1]["content"]
        assert content[0] == {"type": "text", "text": "描述这张图片"}
        assert content[1] == {"type": "image_url", "image_url": {"url": PNG_URL}}
        assert len(content) == 2

    def test_injects_multiple_images_in_order(self):
        agent = _bare_agent()
        messages = [{"role": "user", "content": "比较这两张图"}]

        result = agent._inject_images_as_content(messages, [PNG_URL, JPEG_URL])

        content = result[0]["content"]
        assert len(content) == 3
        assert content[1]["image_url"]["url"] == PNG_URL
        assert content[2]["image_url"]["url"] == JPEG_URL

    def test_empty_messages_returns_empty(self):
        agent = _bare_agent()

        assert agent._inject_images_as_content([], [PNG_URL]) == []

    def test_non_user_tail_is_left_alone(self):
        """末条不是 user 时不跨消息搬运图片。"""
        agent = _bare_agent()
        messages = [
            {"role": "user", "content": "看图"},
            {"role": "assistant", "content": "好的"},
        ]

        result = agent._inject_images_as_content(messages, [PNG_URL])

        assert result == messages
        assert result[0]["content"] == "看图"  # 图片没有回灌到前面的 user 消息

    def test_tool_tail_is_left_alone(self):
        agent = _bare_agent()
        messages = [{"role": "tool", "content": "tool 输出", "tool_call_id": "call_1"}]

        result = agent._inject_images_as_content(messages, [PNG_URL])

        assert result == messages

    def test_does_not_mutate_input(self):
        """不可变性：原列表与其中的 dict 都不得被修改。"""
        agent = _bare_agent()
        messages = [{"role": "user", "content": "描述这张图片"}]
        before = copy.deepcopy(messages)

        result = agent._inject_images_as_content(messages, [PNG_URL])

        assert messages == before
        assert result is not messages
        assert result[0] is not messages[0]
        assert messages[0]["content"] == "描述这张图片"  # 原 content 仍是字符串

    def test_content_already_list_appends_segments(self):
        """LOW-1：content 已是 content-segment 形态时直接追加，不能包成畸形 text。"""
        agent = _bare_agent()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "已有的第一段"},
                    {"type": "text", "text": "已有的第二段"},
                ],
            }
        ]

        result = agent._inject_images_as_content(messages, [PNG_URL])

        content = result[0]["content"]
        assert len(content) == 3
        assert content[0] == {"type": "text", "text": "已有的第一段"}
        assert content[1] == {"type": "text", "text": "已有的第二段"}
        assert content[2] == {"type": "image_url", "image_url": {"url": PNG_URL}}
        # 不能出现 {"type": "text", "text": [...]} 这种畸形段
        assert all(not isinstance(seg.get("text"), list) for seg in content)

    def test_preserves_extra_keys_on_last_message(self):
        agent = _bare_agent()
        messages = [{"role": "user", "content": "hi", "name": "alice"}]

        result = agent._inject_images_as_content(messages, [PNG_URL])

        assert result[0]["name"] == "alice"
        assert result[0]["role"] == "user"

    def test_missing_content_key_defaults_to_empty_text(self):
        agent = _bare_agent()
        messages = [{"role": "user"}]

        result = agent._inject_images_as_content(messages, [PNG_URL])

        assert result[0]["content"][0] == {"type": "text", "text": ""}


class TestModelCapabilities:
    """能力判定：未接 resolver 时乐观按支持处理。"""

    @pytest.mark.asyncio()
    async def test_unknown_capability_is_treated_as_supported(self):
        """resolver 未接线 → 能力未知 → 保守按支持 vision 处理（不回归现有用户）。"""
        agent = _bare_agent()
        assert agent.capability_resolver is None

        caps = await agent._get_model_capabilities("some-unknown-model")

        assert caps == ["chat", "vision"]

    @pytest.mark.asyncio()
    async def test_confirmed_no_vision_excludes_vision(self):
        agent = _bare_agent()
        agent.capability_resolver = lambda model_id: MagicMock(vision=False)

        caps = await agent._get_model_capabilities("gpt-3.5-turbo")

        assert caps == ["chat"]

    @pytest.mark.asyncio()
    async def test_confirmed_vision_includes_vision(self):
        agent = _bare_agent()
        agent.capability_resolver = lambda model_id: MagicMock(vision=True)

        caps = await agent._get_model_capabilities("gpt-4o")

        assert caps == ["chat", "vision"]

    @pytest.mark.asyncio()
    async def test_resolver_returning_none_is_unknown_not_false(self):
        """resolver 明确返回 None = 未知，不得当成「不支持」。"""
        agent = _bare_agent()
        agent.capability_resolver = lambda model_id: None

        caps = await agent._get_model_capabilities("whatever")

        assert caps == ["chat", "vision"]

    @pytest.mark.asyncio()
    async def test_resolver_raising_degrades_to_unknown(self):
        """能力探测异常不应让图片流程崩掉，退回未知（乐观注入）。"""
        agent = _bare_agent()

        def boom(model_id):
            raise RuntimeError("provider 挂了")

        agent.capability_resolver = boom

        caps = await agent._get_model_capabilities("gpt-4o")

        assert caps == ["chat", "vision"]


class TestResolveChatModelId:
    def test_reads_model_from_llm_config(self):
        agent = _bare_agent(model="gpt-4.1")

        assert agent._resolve_chat_model_id() == "gpt-4.1"

    def test_none_config_yields_empty_string(self):
        agent = _bare_agent()
        agent.llm_config = None

        assert agent._resolve_chat_model_id() == ""


class TestVisionFallback:
    """Test intelligent vision fallback strategy."""

    @pytest.mark.asyncio()
    async def test_chat_model_supports_vision(self):
        """chatModel 支持 vision 时，直接注入图片，不调用 visionModel。"""
        # Arrange
        agent = MagicMock(spec=SageAgent)
        agent._get_model_capabilities = AsyncMock(return_value=["chat", "vision"])
        agent._inject_images_as_content = MagicMock(
            return_value=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "描述这张图片"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,..."},
                        },
                    ],
                }
            ]
        )

        messages = [{"role": "user", "content": "描述这张图片"}]
        images = ["data:image/png;base64,..."]

        # Act
        result = await SageAgent._prepare_messages_with_images(agent, messages, images)

        # Assert
        assert len(result) == 1
        assert result[0]["content"][1]["type"] == "image_url"
        agent._inject_images_as_content.assert_called_once_with(messages, images)

    @pytest.mark.asyncio()
    async def test_no_images_passthrough_untouched(self):
        """无图时不走能力判定，直接透传原消息。"""
        agent = MagicMock(spec=SageAgent)
        agent._get_model_capabilities = AsyncMock(return_value=["chat"])
        messages = [{"role": "user", "content": "纯文本"}]

        result = await SageAgent._prepare_messages_with_images(agent, messages, [])

        assert result is messages
        agent._get_model_capabilities.assert_not_called()
