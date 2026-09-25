"""R125 — multimodal 工具封装层单元测试（TTS / ASR / ImageGen）。

覆盖：schema 契约（名称/required/risk）、未配置模型的友好失败、
事件循环外直跑与循环内线程池双通路、异常到 ToolResult 的映射、
ASR FileNotFoundError 专属文案、ImageGen 参数透传。
capability 层全部 monkeypatch，不发真实网络请求。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.domain.risk import RiskClass
from backend.tools.asr_tool import SpeechToTextTool
from backend.tools.image_gen_tool import ImageGenerationTool
from backend.tools.tts_tool import TextToSpeechTool

pytestmark = pytest.mark.unit


def _media_ref(api_url="/api/v1/media/abc"):
    return SimpleNamespace(api_url=api_url)


def _patch_capability(monkeypatch, cap_cls, execute_result=None, execute_exc=None):
    """类级替换 load_config/execute，隔离 settings 与网络。"""
    monkeypatch.setattr(cap_cls, "load_config", lambda self: SimpleNamespace(base_url="x"))
    calls = {}

    async def fake_execute(self, config, **kwargs):
        calls.update(kwargs)
        if execute_exc is not None:
            raise execute_exc
        return execute_result

    monkeypatch.setattr(cap_cls, "execute", fake_execute)
    return calls


# ---------------------------------------------------------------------------
# schema 契约
# ---------------------------------------------------------------------------


def test_tts_schema_contract():
    schema = TextToSpeechTool().schema
    assert schema.name == "text_to_speech"
    assert schema.parameters["required"] == ["text"]


def test_asr_schema_contract():
    schema = SpeechToTextTool().schema
    assert schema.name == "speech_to_text"
    assert schema.parameters["required"] == ["file_path"]


def test_imagegen_schema_contract():
    schema = ImageGenerationTool().schema
    assert schema.name == "generate_image"
    assert schema.parameters["required"] == ["prompt"]


def test_risk_classes():
    assert TextToSpeechTool.risk == RiskClass.WRITE_LOCAL
    assert SpeechToTextTool.risk == RiskClass.READ
    assert ImageGenerationTool.risk == RiskClass.WRITE_LOCAL


# ---------------------------------------------------------------------------
# 未配置模型
# ---------------------------------------------------------------------------


def test_tts_without_config_fails_friendly(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    monkeypatch.setattr(TTSCapability, "load_config", lambda self: None)
    out = TextToSpeechTool().execute(text="你好")
    assert out.success is False
    assert "未配置" in out.error


def test_asr_without_config_fails_friendly(monkeypatch):
    from backend.services.multimodal.asr import ASRCapability

    monkeypatch.setattr(ASRCapability, "load_config", lambda self: None)
    out = SpeechToTextTool().execute(file_path="a.wav")
    assert out.success is False
    assert "未配置" in out.error


def test_imagegen_without_config_fails_friendly(monkeypatch):
    from backend.services.multimodal.image_gen import ImageGenCapability

    monkeypatch.setattr(ImageGenCapability, "load_config", lambda self: None)
    out = ImageGenerationTool().execute(prompt="cat")
    assert out.success is False
    assert "未配置" in out.error


# ---------------------------------------------------------------------------
# 成功路径：循环外直跑
# ---------------------------------------------------------------------------


def test_tts_success_outside_loop(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    calls = _patch_capability(monkeypatch, TTSCapability, execute_result=_media_ref())
    out = TextToSpeechTool().execute(text="你好", voice="nova", speed=1.5)
    assert out.success is True
    assert out.output["api_url"] == "/api/v1/media/abc"
    assert "api/v1/media" in out.content
    assert calls["voice"] == "nova"
    assert calls["speed"] == 1.5


def test_asr_success_outside_loop(monkeypatch):
    from backend.services.multimodal.asr import ASRCapability

    calls = _patch_capability(
        monkeypatch, ASRCapability, execute_result={"text": "识别文本", "language": "zh"}
    )
    out = SpeechToTextTool().execute(file_path="a.wav", language="zh")
    assert out.success is True
    assert out.content == "识别文本"
    assert out.output["language"] == "zh"
    assert calls["file_path"] == "a.wav"


def test_imagegen_success_outside_loop(monkeypatch):
    from backend.services.multimodal.image_gen import ImageGenCapability

    refs = [_media_ref("/api/v1/media/img1")]
    calls = _patch_capability(monkeypatch, ImageGenCapability, execute_result=refs)
    out = ImageGenerationTool().execute(prompt="a cat", size="512x512")
    assert out.success is True
    assert out.output["media_refs"] == refs
    assert calls["prompt"] == "a cat"
    assert calls["size"] == "512x512"


# ---------------------------------------------------------------------------
# 成功路径：事件循环内（线程池通路）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_tts_success_inside_loop(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    _patch_capability(monkeypatch, TTSCapability, execute_result=_media_ref("/in-loop"))
    out = TextToSpeechTool().execute(text="hi")
    assert out.success is True
    assert out.output["api_url"] == "/in-loop"


@pytest.mark.asyncio()
async def test_asr_success_inside_loop(monkeypatch):
    from backend.services.multimodal.asr import ASRCapability

    _patch_capability(
        monkeypatch, ASRCapability, execute_result={"text": "loop", "language": "en"}
    )
    out = SpeechToTextTool().execute(file_path="a.wav")
    assert out.success is True
    assert out.content == "loop"


# ---------------------------------------------------------------------------
# 异常映射
# ---------------------------------------------------------------------------


def test_tts_exception_maps_to_error_result(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    _patch_capability(monkeypatch, TTSCapability, execute_exc=RuntimeError("boom"))
    out = TextToSpeechTool().execute(text="x")
    assert out.success is False
    assert "TTS 生成失败" in out.error


def test_asr_file_not_found_friendly(monkeypatch):
    from backend.services.multimodal.asr import ASRCapability

    _patch_capability(monkeypatch, ASRCapability, execute_exc=FileNotFoundError("gone"))
    out = SpeechToTextTool().execute(file_path="missing.wav")
    assert out.success is False
    assert "音频文件不存在" in out.error


def test_imagegen_exception_maps_to_error_result(monkeypatch):
    from backend.services.multimodal.image_gen import ImageGenCapability

    _patch_capability(monkeypatch, ImageGenCapability, execute_exc=ValueError("bad"))
    out = ImageGenerationTool().execute(prompt="x")
    assert out.success is False
    assert out.error is not None
