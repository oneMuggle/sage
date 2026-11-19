"""Task 8 (M5): 浏览器截图临时视觉/OCR 反馈注入单测。

覆盖 ``SageAgent._maybe_attach_tool_image_feedback`` 的三条路径：

1. 视觉模型 → 临时 user 消息（文本 + image_url）；
2. 无视觉 + 本地 OCR → OCR 文本；
3. 都不满足 → 可操作提示文本（不抛异常）。

同时验证临时消息的生命周期：每轮按固定标记清理、不残留、不被当成
普通历史；以及截图 data URL 超过工具结果截断上限时仍能经旁路字段注入。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import (
    _TOOL_IMAGE_FEEDBACK_OCR_HEADER,
    _TOOL_IMAGE_FEEDBACK_UNAVAILABLE,
    _TOOL_IMAGE_FEEDBACK_VISION_TEXT,
    TOOL_IMAGE_FEEDBACK_MARKER,
    SageAgent,
    _tool_image_payload_from_content,
)
from backend.core.legacy.llm_client import LLMConfig

PNG_URL = "data:image/png;base64,AAAA"


def _bare_agent(with_vision: bool = True) -> SageAgent:
    agent = SageAgent.__new__(SageAgent)
    agent.llm_config = LLMConfig(
        model="gpt-4o" if with_vision else "gpt-3.5-turbo", provider="openai"
    )
    agent.capability_resolver = lambda model_id: MagicMock(vision=with_vision)
    agent._pending_tool_image_feedback = None
    return agent


def _image_tool_message(path: str = "/tmp/shot.png") -> dict:
    return {
        "role": "tool",
        "tool_call_id": "call_shot",
        "content": json.dumps(
            {
                "path": path,
                "bytes": 123,
                "attach_image_to_next_turn": True,
                "image_data_url": PNG_URL,
                "image_bytes": 123,
            },
            ensure_ascii=False,
        ),
    }


def _transient_messages(messages):
    return [m for m in messages if SageAgent._is_tool_image_feedback_message(m)]


class TestVisionInjection:
    @pytest.mark.asyncio()
    async def test_attaches_image_for_vision_model(self):
        agent = _bare_agent(with_vision=True)
        messages = [{"role": "assistant", "content": "先看页面"}, _image_tool_message()]

        injected = await agent._maybe_attach_tool_image_feedback(messages)

        assert injected is True
        assert len(messages) == 3
        transient = messages[-1]
        assert transient["role"] == "user"
        assert transient["content"][0] == {
            "type": "text",
            "text": TOOL_IMAGE_FEEDBACK_MARKER + _TOOL_IMAGE_FEEDBACK_VISION_TEXT,
        }
        assert transient["content"][1] == {
            "type": "image_url",
            "image_url": {"url": PNG_URL},
        }

    @pytest.mark.asyncio()
    async def test_previous_transient_is_replaced_each_iteration(self):
        agent = _bare_agent(with_vision=True)
        messages = [_image_tool_message()]

        assert await agent._maybe_attach_tool_image_feedback(messages) is True
        assert len(_transient_messages(messages)) == 1

        # 下一轮迭代：旧临时消息先被移除，再按同一工具结果重新注入 — 仍只有一条
        assert await agent._maybe_attach_tool_image_feedback(messages) is True
        assert len(_transient_messages(messages)) == 1
        assert messages[-1]["role"] == "user"

    @pytest.mark.asyncio()
    async def test_transient_removed_when_no_new_image_result(self):
        agent = _bare_agent(with_vision=True)
        messages = [_image_tool_message()]
        await agent._maybe_attach_tool_image_feedback(messages)

        # 新工具结果不带截图 → 旧临时消息被清掉，且不再注入
        messages.append({"role": "tool", "tool_call_id": "call_2", "content": "clicked"})

        assert await agent._maybe_attach_tool_image_feedback(messages) is False
        assert _transient_messages(messages) == []
        assert all(m.get("role") != "user" for m in messages)

    @pytest.mark.asyncio()
    async def test_pending_side_channel_survives_truncated_tool_message(self):
        """data URL 被 100KB 上限截断后，旁路字段仍提供原始附件。"""
        agent = _bare_agent(with_vision=True)
        agent._pending_tool_image_feedback = {
            "image_data_url": PNG_URL,
            "path": "/tmp/shot.png",
        }
        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_shot",
                "content": '{"path": "/tmp/shot.png", "attach_image_to_next_tur',
            }
        ]

        assert await agent._maybe_attach_tool_image_feedback(messages) is True
        assert messages[-1]["content"][1]["image_url"]["url"] == PNG_URL
        assert agent._pending_tool_image_feedback is None

    @pytest.mark.asyncio()
    async def test_transient_not_replayed_after_assistant_reply(self):
        agent = _bare_agent(with_vision=True)
        messages = [
            _image_tool_message(),
            {"role": "assistant", "content": "这是登录页"},
        ]

        assert await agent._maybe_attach_tool_image_feedback(messages) is False
        assert _transient_messages(messages) == []


class TestOcrAndHintFallback:
    @pytest.mark.asyncio()
    async def test_no_vision_uses_local_ocr_text(self):
        agent = _bare_agent(with_vision=False)
        agent._local_ocr_available = lambda: True
        agent._ocr_screenshot_for_feedback = AsyncMock(
            return_value=_TOOL_IMAGE_FEEDBACK_OCR_HEADER + "\nHELLO OCR"
        )
        messages = [_image_tool_message()]

        assert await agent._maybe_attach_tool_image_feedback(messages) is True

        content = messages[-1]["content"]
        assert isinstance(content, str)
        assert content.startswith(TOOL_IMAGE_FEEDBACK_MARKER)
        assert "HELLO OCR" in content
        agent._ocr_screenshot_for_feedback.assert_awaited_once_with("/tmp/shot.png")

    @pytest.mark.asyncio()
    async def test_no_vision_no_ocr_returns_actionable_hint(self):
        agent = _bare_agent(with_vision=False)
        agent._local_ocr_available = lambda: False
        messages = [_image_tool_message()]

        assert await agent._maybe_attach_tool_image_feedback(messages) is True

        content = messages[-1]["content"]
        assert content == TOOL_IMAGE_FEEDBACK_MARKER + _TOOL_IMAGE_FEEDBACK_UNAVAILABLE
        assert "browser_snapshot" in content

    @pytest.mark.asyncio()
    async def test_ocr_failure_degrades_to_hint_without_raising(self):
        agent = _bare_agent(with_vision=False)
        agent._local_ocr_available = lambda: True
        agent._ocr_screenshot_for_feedback = AsyncMock(return_value="")
        messages = [_image_tool_message()]

        assert await agent._maybe_attach_tool_image_feedback(messages) is True
        assert _TOOL_IMAGE_FEEDBACK_UNAVAILABLE in messages[-1]["content"]

    @pytest.mark.asyncio()
    async def test_ocr_helper_uses_service_and_returns_text(self, monkeypatch):
        import backend.services.ocr as ocr_module

        agent = _bare_agent(with_vision=False)
        result = SimpleNamespace(ok=True, text="  页面标题  ")
        service = SimpleNamespace(recognize_path=lambda path, lang="auto": result)
        monkeypatch.setattr(ocr_module, "get_ocr_service", lambda: service)

        text = await agent._ocr_screenshot_for_feedback("/tmp/shot.png")

        assert text == _TOOL_IMAGE_FEEDBACK_OCR_HEADER + "\n页面标题"

    @pytest.mark.asyncio()
    async def test_ocr_helper_swallows_service_failure(self, monkeypatch):
        import backend.services.ocr as ocr_module

        agent = _bare_agent(with_vision=False)

        def _boom():
            raise RuntimeError("ocr 引擎初始化失败")

        monkeypatch.setattr(ocr_module, "get_ocr_service", _boom)

        assert await agent._ocr_screenshot_for_feedback("/tmp/shot.png") == ""


class TestPayloadExtraction:
    @pytest.mark.asyncio()
    async def test_plain_tool_result_never_injects(self):
        agent = _bare_agent(with_vision=True)
        messages = [{"role": "tool", "tool_call_id": "c1", "content": "普通工具输出"}]

        assert await agent._maybe_attach_tool_image_feedback(messages) is False
        assert len(messages) == 1

    @pytest.mark.asyncio()
    async def test_invalid_json_never_injects(self):
        agent = _bare_agent(with_vision=True)
        messages = [
            {"role": "tool", "tool_call_id": "c1", "content": "{attach_image_to_next_turn"}
        ]

        assert await agent._maybe_attach_tool_image_feedback(messages) is False
        assert len(messages) == 1

    def test_payload_requires_attach_flag_and_data_url(self):
        assert _tool_image_payload_from_content("plain text") is None
        assert (
            _tool_image_payload_from_content(json.dumps({"attach_image_to_next_turn": True}))
            is None
        )
        assert (
            _tool_image_payload_from_content(
                json.dumps({"attach_image_to_next_turn": False, "image_data_url": PNG_URL})
            )
            is None
        )
        assert (
            _tool_image_payload_from_content(
                json.dumps({"attach_image_to_next_turn": True, "image_data_url": "https://x/"})
            )
            is None
        )
        assert _tool_image_payload_from_content(
            json.dumps(
                {
                    "attach_image_to_next_turn": True,
                    "image_data_url": PNG_URL,
                    "path": "/tmp/a.png",
                }
            )
        ) == {"image_data_url": PNG_URL, "path": "/tmp/a.png"}

    def test_marker_detection_handles_text_and_segment_content(self):
        assert SageAgent._is_tool_image_feedback_message(
            {"role": "user", "content": TOOL_IMAGE_FEEDBACK_MARKER + "hi"}
        )
        assert SageAgent._is_tool_image_feedback_message(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TOOL_IMAGE_FEEDBACK_MARKER + "hi"},
                    {"type": "image_url", "image_url": {"url": PNG_URL}},
                ],
            }
        )
        assert not SageAgent._is_tool_image_feedback_message(
            {"role": "user", "content": "普通用户消息"}
        )
        assert not SageAgent._is_tool_image_feedback_message(
            {"role": "assistant", "content": TOOL_IMAGE_FEEDBACK_MARKER + "hi"}
        )
