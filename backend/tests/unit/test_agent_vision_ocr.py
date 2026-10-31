"""聊天图片本地 OCR 兜底测试（fake 引擎，无真实 OCR 依赖）。"""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.exceptions import VisionNotAvailableError
from backend.core.legacy.agent import SageAgent
from backend.core.legacy.llm_client import LLMConfig
from backend.services.ocr import (
    OcrConfig,
    OcrLine,
    OcrResult,
    OcrService,
    init_ocr_service,
    reset_ocr_service,
)

PNG_URL = "data:image/png;base64,AAAA"


class FakeEngine:
    name = "fake-ocr"

    def __init__(self, available: bool = True, error: str = "") -> None:
        self._available = available
        self.error = error
        self.calls = 0

    def available(self):
        return (self._available, "" if self._available else "missing")

    def recognize(self, image_bytes, opts):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return OcrResult(
            text="识别出的文字",
            lines=(OcrLine(text="识别出的文字", confidence=0.92),),
            engine=self.name,
            lang=opts.lang,
        )


@pytest.fixture(autouse=True)
def _isolate_service():
    reset_ocr_service()
    yield
    reset_ocr_service()


def _agent(
    *,
    vision: bool = False,
    vision_model: bool = False,
    prefer_local: bool = False,
    engine: FakeEngine = None,
) -> SageAgent:
    agent = SageAgent.__new__(SageAgent)
    agent.llm_config = LLMConfig(model="test-model", provider="openai")
    agent.capability_resolver = lambda _model_id: MagicMock(vision=vision)
    agent._is_vision_model_configured = lambda: vision_model
    init_ocr_service(
        OcrService(
            engines=[engine or FakeEngine()],
            config_provider=lambda: OcrConfig(
                enabled=True,
                engine="auto",
                lang="auto",
                prefer_local_for_images=prefer_local,
            ),
        )
    )
    return agent


def _text_of(messages) -> str:
    content = messages[-1]["content"]
    if isinstance(content, list):
        return "\n".join(seg.get("text", "") for seg in content)
    return str(content)


@pytest.mark.asyncio()
async def test_no_vision_and_no_vision_model_uses_local_ocr() -> None:
    agent = _agent(vision=False, vision_model=False)

    result = await agent._prepare_messages_with_images(
        [{"role": "user", "content": "这张截图写了什么"}], [PNG_URL]
    )

    text = _text_of(result)
    assert "本地 OCR" in text
    assert "识别出的文字" in text
    assert "这张截图写了什么" in text


@pytest.mark.asyncio()
async def test_native_vision_wins_by_default() -> None:
    agent = _agent(vision=True)

    result = await agent._prepare_messages_with_images(
        [{"role": "user", "content": "看图"}], [PNG_URL]
    )

    content = result[-1]["content"]
    assert any(seg.get("type") == "image_url" for seg in content)
    assert "本地 OCR" not in _text_of(result)


@pytest.mark.asyncio()
async def test_prefer_local_ocr_overrides_native_vision() -> None:
    agent = _agent(vision=True, prefer_local=True)

    result = await agent._prepare_messages_with_images(
        [{"role": "user", "content": "看图"}], [PNG_URL]
    )

    assert "本地 OCR" in _text_of(result)
    assert not any(seg.get("type") == "image_url" for seg in result[-1]["content"])


@pytest.mark.asyncio()
async def test_vision_model_still_precedes_local_ocr() -> None:
    agent = _agent(vision=False, vision_model=True)
    agent._generate_image_descriptions = AsyncMock(return_value=["视觉模型描述"])

    result = await agent._prepare_messages_with_images(
        [{"role": "user", "content": "看图"}], [PNG_URL]
    )

    text = _text_of(result)
    assert "视觉模型描述" in text
    assert "本地 OCR" not in text


@pytest.mark.asyncio()
async def test_provided_ocr_texts_are_used_without_engine_call() -> None:
    engine = FakeEngine()
    agent = _agent(vision=False, vision_model=False, engine=engine)

    result = await agent._prepare_messages_with_images(
        [{"role": "user", "content": "看图"}], [PNG_URL], ["用户编辑后的文字"]
    )

    text = _text_of(result)
    assert "用户编辑后的文字" in text
    assert "用户确认" in text
    assert engine.calls == 0


@pytest.mark.asyncio()
async def test_mismatched_provided_texts_fall_back_to_ocr() -> None:
    engine = FakeEngine()
    agent = _agent(vision=False, vision_model=False, engine=engine)

    result = await agent._prepare_messages_with_images(
        [{"role": "user", "content": "看图"}], [PNG_URL], ["one", "two"]
    )

    text = _text_of(result)
    assert "识别出的文字" in text
    assert engine.calls == 1


@pytest.mark.asyncio()
async def test_ocr_failure_becomes_placeholder_not_exception() -> None:
    agent = _agent(vision=False, vision_model=False, engine=FakeEngine(error="boom"))

    result = await agent._prepare_messages_with_images(
        [{"role": "user", "content": "看图"}], [PNG_URL]
    )

    text = _text_of(result)
    assert "文字识别失败" in text
    assert "boom" in text


@pytest.mark.asyncio()
async def test_no_engine_raises_vision_not_available() -> None:
    agent = _agent(
        vision=False, vision_model=False, engine=FakeEngine(available=False)
    )

    with pytest.raises(VisionNotAvailableError):
        await agent._prepare_messages_with_images(
            [{"role": "user", "content": "看图"}], [PNG_URL]
        )


def test_replace_images_with_text_does_not_mutate_input() -> None:
    agent = _agent(vision=False)
    messages = [{"role": "user", "content": "原始文本", "name": "alice"}]
    before = copy.deepcopy(messages)

    result = agent._replace_images_with_text(
        messages, ["[图片 1 文字内容 · 本地 OCR]\nhello"]
    )

    assert messages == before
    assert result is not messages
    assert result[0]["name"] == "alice"
    assert "hello" in result[0]["content"][0]["text"]


def test_format_ocr_text_marks_low_confidence() -> None:
    result = OcrResult(
        text="低置信度文本",
        engine="fake-ocr",
        quality="low_confidence",
    )

    formatted = SageAgent._format_ocr_text(1, result)

    assert "置信度较低" in formatted
    assert "低置信度文本" in formatted


def test_format_ocr_text_empty_result() -> None:
    formatted = SageAgent._format_ocr_text(1, OcrResult(text="", engine="fake-ocr"))

    assert "未识别到文字" in formatted
