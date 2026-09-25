"""R118 — multimodal 能力层单元测试（TTS + ImageGen）。

覆盖：build_request 的 URL/头部/body 构建（api_key 有无、缺省值、固定
response_format）、parse_response 的非 200 错误路径与 200 落库路径
（kind/source/ext/metadata 截断与转义）。MediaStore 用捕获型 fake 隔离，
另以真 store(root=tmp_path) 验证落盘真实性。
"""

from __future__ import annotations

import base64

import pytest

from backend.services.multimodal import image_gen as ig_mod, tts as tts_mod
from backend.services.multimodal.capability import (
    AIHttpResponse,
    CapabilityConfig,
)
from backend.services.multimodal.image_gen import ImageGenCapability
from backend.services.multimodal.media_store import MediaKind, MediaRef, MediaStore
from backend.services.multimodal.tts import TTSCapability

pytestmark = pytest.mark.unit


class _FakeStore:
    """捕获 save() 实参的替身存储。"""

    def __init__(self, ref=None):
        self.ref = ref or MediaRef(
            id="deadbeef0000",
            kind=MediaKind.AUDIO,
            mime_type="audio/mpeg",
            file_path="2026/09/24/deadbeef0000.mp3",
            file_size=3,
            created_at="2026-09-24T00:00:00+00:00",
            source="tts",
            metadata={},
        )
        self.calls = []

    def save(self, content, kind, source, metadata=None, ext=None):
        self.calls.append(
            {
                "content": content,
                "kind": kind,
                "source": source,
                "metadata": metadata,
                "ext": ext,
            }
        )
        return self.ref


def _config(api_key: str = "") -> CapabilityConfig:
    return CapabilityConfig(
        base_url="https://api.example.com/v1", api_key=api_key, model="demo-model"
    )


def _resp(status_code=200, content=b"", json=None):
    return AIHttpResponse(status_code=status_code, content=content, json=json)


# ---------------------------------------------------------------------------
# TTSCapability.build_request
# ---------------------------------------------------------------------------


def test_tts_build_request_shape():
    req = TTSCapability().build_request(
        _config(api_key="sk-test"), text="你好", voice="nova", speed=1.5
    )
    assert req.url == "https://api.example.com/v1/audio/speech"
    assert req.method == "POST"
    assert req.timeout == 120.0
    assert req.headers["Authorization"] == "Bearer sk-test"
    assert req.headers["Content-Type"] == "application/json"
    assert req.body == {
        "model": "demo-model",
        "input": "你好",
        "voice": "nova",
        "response_format": "mp3",
        "speed": 1.5,
    }


def test_tts_build_request_defaults_without_api_key():
    req = TTSCapability().build_request(_config(), text="hi")
    assert "Authorization" not in req.headers
    assert req.body["voice"] == "alloy"
    assert req.body["speed"] == 1.0
    assert req.body["response_format"] == "mp3"


def test_tts_kind_and_settings_slot():
    cap = TTSCapability()
    assert cap.settings_slot == "ttsModel"


# ---------------------------------------------------------------------------
# TTSCapability.parse_response
# ---------------------------------------------------------------------------


def test_tts_parse_response_non_200_raises():
    with pytest.raises(ValueError, match="TTS upstream returned 500"):
        TTSCapability().parse_response(_resp(500, content=b"boom"))
    with pytest.raises(ValueError, match="错误"):
        TTSCapability().parse_response(_resp(503, content="错误".encode()))


def test_tts_parse_response_saves_audio(monkeypatch):
    fake = _FakeStore()
    monkeypatch.setattr(tts_mod, "MediaStore", lambda: fake)
    ref = TTSCapability().parse_response(
        _resp(200, content=b"mp3-bytes"),
        text="你好世界",
        response_format="opus",
    )
    assert ref is fake.ref
    call = fake.calls[0]
    assert call["content"] == b"mp3-bytes"
    assert call["kind"] == MediaKind.AUDIO
    assert call["source"] == "tts"
    assert call["ext"] == "opus"
    assert call["metadata"]["text_preview"] == "你好世界"


def test_tts_text_preview_truncated_to_100(monkeypatch):
    fake = _FakeStore()
    monkeypatch.setattr(tts_mod, "MediaStore", lambda: fake)
    TTSCapability().parse_response(_resp(200, content=b"x"), text="字" * 150)
    assert fake.calls[0]["metadata"]["text_preview"] == "字" * 100


def test_tts_parse_response_uses_real_store(monkeypatch, tmp_path):
    """真实 MediaStore(root=tmp_path) 落盘：文件存在且大小正确。"""
    real = MediaStore(root=tmp_path)
    monkeypatch.setattr(tts_mod, "MediaStore", lambda: real)
    ref = TTSCapability().parse_response(
        _resp(200, content=b"abc"), text="t", response_format="mp3"
    )
    assert isinstance(ref, MediaRef)
    assert ref.file_size == 3
    assert (real.root / ref.file_path).read_bytes() == b"abc"


# ---------------------------------------------------------------------------
# ImageGenCapability.build_request
# ---------------------------------------------------------------------------


def test_imagegen_build_request_shape():
    req = ImageGenCapability().build_request(
        _config(api_key="sk-img"), prompt="a cat", size="512x512", n=2
    )
    assert req.url == "https://api.example.com/v1/images/generations"
    assert req.timeout == 120.0
    assert req.headers["Authorization"] == "Bearer sk-img"
    assert req.body == {
        "model": "demo-model",
        "prompt": "a cat",
        "size": "512x512",
        "quality": "standard",
        "n": 2,
        "response_format": "b64_json",
    }


def test_imagegen_response_format_always_b64(monkeypatch):
    # quality 显式覆盖 + response_format 不暴露给调用方（固定 b64_json）
    req = ImageGenCapability().build_request(_config(), prompt="p", quality="hd")
    assert req.body["quality"] == "hd"
    assert req.body["response_format"] == "b64_json"


def test_imagegen_kind_and_settings_slot():
    assert ImageGenCapability().settings_slot == "imageGenModel"


# ---------------------------------------------------------------------------
# ImageGenCapability.parse_response
# ---------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_imagegen_parse_response_non_200_raises():
    with pytest.raises(ValueError, match="ImageGen upstream returned 429"):
        ImageGenCapability().parse_response(_resp(429, content=b"rate limited"))


def test_imagegen_parse_response_decodes_items(monkeypatch):
    fake = _FakeStore()
    monkeypatch.setattr(ig_mod, "MediaStore", lambda: fake)
    refs = ImageGenCapability().parse_response(
        _resp(200, json={"data": [
            {"b64_json": _b64(b"png1"), "revised_prompt": "a fluffy cat"},
            {"b64_json": _b64(b"png2")},
        ]}),
        prompt="a cat",
    )
    assert refs == [fake.ref, fake.ref]
    assert [c["content"] for c in fake.calls] == [b"png1", b"png2"]
    assert all(c["kind"] == MediaKind.IMAGE for c in fake.calls)
    assert all(c["source"] == "image_gen" for c in fake.calls)
    assert all(c["ext"] == "png" for c in fake.calls)
    assert fake.calls[0]["metadata"]["revised_prompt"] == "a fluffy cat"
    assert fake.calls[0]["metadata"]["prompt"] == "a cat"
    assert fake.calls[1]["metadata"]["revised_prompt"] == ""


def test_imagegen_items_without_b64_skipped(monkeypatch):
    fake = _FakeStore()
    monkeypatch.setattr(ig_mod, "MediaStore", lambda: fake)
    refs = ImageGenCapability().parse_response(
        _resp(200, json={"data": [{"url": "https://x/y.png"}, {}]}),
        prompt="p",
    )
    assert refs == []
    assert fake.calls == []


def test_imagegen_empty_data_and_missing_json(monkeypatch):
    fake = _FakeStore()
    monkeypatch.setattr(ig_mod, "MediaStore", lambda: fake)
    assert ImageGenCapability().parse_response(_resp(200, json={"data": []})) == []
    assert ImageGenCapability().parse_response(_resp(200, json=None)) == []
    assert fake.calls == []
