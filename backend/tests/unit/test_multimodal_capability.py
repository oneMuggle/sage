"""多模态能力抽象层单元测试"""

import pytest

pytestmark = [pytest.mark.unit]


def test_capability_kind_enum():
    from backend.services.multimodal.capability import CapabilityKind
    assert CapabilityKind.TTS.value == "tts"
    assert CapabilityKind.ASR.value == "asr"
    assert CapabilityKind.IMAGE_GEN.value == "image_gen"


def test_capability_config_frozen():
    from backend.services.multimodal.capability import CapabilityConfig
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="tts-1")
    assert config.base_url == "https://api.example.com"
    assert config.api_key == "sk-test"
    assert config.model == "tts-1"
    assert config.extra == {}
    with pytest.raises(AttributeError):
        config.base_url = "changed"


def test_http_request_defaults():
    from backend.services.multimodal.capability import AIHttpRequest
    req = AIHttpRequest(url="https://api.example.com/v1/audio/speech")
    assert req.method == "POST"
    assert req.timeout == 60.0
    assert req.body is None
    assert req.data is None


def test_http_response_fields():
    from backend.services.multimodal.capability import AIHttpResponse
    resp = AIHttpResponse(status_code=200, content=b"hello")
    assert resp.json is None
    assert resp.content_type == ""


def test_registry_register_and_get():
    from backend.services.multimodal.registry import CapabilityRegistry
    from backend.services.multimodal.capability import AICapability, CapabilityKind, CapabilityConfig, AIHttpRequest, AIHttpResponse

    class DummyCapability(AICapability):
        kind = CapabilityKind.TTS
        settings_slot = "ttsModel"
        def build_request(self, config, **kw): return AIHttpRequest(url="http://x")
        def parse_response(self, resp, **kw): return None

    CapabilityRegistry.register(DummyCapability())
    assert CapabilityRegistry.get(CapabilityKind.TTS) is not None
    assert CapabilityKind.TTS in CapabilityRegistry.all_kinds()
    # 清理
    CapabilityRegistry._capabilities.pop(CapabilityKind.TTS, None)


def test_registry_available_empty():
    from backend.services.multimodal.registry import CapabilityRegistry
    saved = CapabilityRegistry._capabilities.copy()
    CapabilityRegistry._capabilities.clear()
    assert CapabilityRegistry.available() == []
    CapabilityRegistry._capabilities = saved


# ── Task 2.1: TTSCapability ──────────────────────────────────


def test_tts_build_request():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.tts import TTSCapability
    cap = TTSCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="tts-1")
    req = cap.build_request(config, text="Hello world", voice="alloy", speed=1.0)
    assert req.url == "https://api.example.com/audio/speech"
    assert req.headers["Authorization"] == "Bearer sk-test"
    assert req.body["model"] == "tts-1"
    assert req.body["input"] == "Hello world"
    assert req.body["voice"] == "alloy"
    assert req.timeout == 120.0


def test_tts_build_request_no_api_key():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.tts import TTSCapability
    cap = TTSCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="", model="tts-1")
    req = cap.build_request(config, text="Hello")
    assert "Authorization" not in req.headers


def test_tts_parse_response_saves_file(tmp_path, monkeypatch):
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.media_store import MediaKind, MediaStore
    from backend.services.multimodal.tts import TTSCapability

    cap = TTSCapability()
    monkeypatch.setattr("backend.services.multimodal.tts.MediaStore",
                        lambda: MediaStore(root=tmp_path))
    resp = AIHttpResponse(status_code=200, content=b'\xff\xfb\x90\x00' + b'\x00' * 50)
    ref = cap.parse_response(resp, text="Hello world test")
    assert ref.kind == MediaKind.AUDIO
    assert ref.source == "tts"
    assert ref.file_size == 54


def test_tts_parse_response_error():
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.tts import TTSCapability
    cap = TTSCapability()
    resp = AIHttpResponse(status_code=401, content=b'{"error": "invalid key"}')
    with pytest.raises(ValueError, match="401"):
        cap.parse_response(resp)


# ── Task 3.1: ASRCapability ──────────────────────────────────


def test_asr_build_request_from_file_content():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="whisper-1")
    req = cap.build_request(config, file_content=b"fake audio data", language="zh")
    assert req.url == "https://api.example.com/audio/transcriptions"
    assert req.headers["Authorization"] == "Bearer sk-test"
    assert req.data is not None


def test_asr_build_request_from_file_path(tmp_path):
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.asr import ASRCapability
    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"fake audio data")
    cap = ASRCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="", model="whisper-1")
    req = cap.build_request(config, file_path=str(audio_file))
    assert req.url == "https://api.example.com/audio/transcriptions"


def test_asr_build_request_no_input_raises():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="", model="whisper-1")
    with pytest.raises(ValueError, match="必须提供"):
        cap.build_request(config)


def test_asr_parse_response_success():
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    resp = AIHttpResponse(
        status_code=200,
        content='{"text": "你好世界", "language": "zh"}'.encode("utf-8"),
        json={"text": "你好世界", "language": "zh"},
        content_type="application/json",
    )
    result = cap.parse_response(resp)
    assert result["text"] == "你好世界"
    assert result["language"] == "zh"


def test_asr_parse_response_error():
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    resp = AIHttpResponse(status_code=500, content=b'error')
    with pytest.raises(ValueError, match="500"):
        cap.parse_response(resp)


def test_asr_build_request_produces_multipart():
    """Verify that ASR request, when built by httpx, has content-type: multipart/form-data."""
    import httpx
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.asr import ASRCapability
    cap = ASRCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="whisper-1")
    req = cap.build_request(config, file_content=b"fake audio data", language="zh")

    # Build the actual httpx request to verify multipart encoding
    client = httpx.Client()
    try:
        httpx_req = client.build_request(
            method=req.method,
            url=req.url,
            headers=req.headers,
            data=req.data,
            files=req.files,
        )
        content_type = httpx_req.headers.get("content-type", "")
        assert content_type.startswith("multipart/form-data")
    finally:
        client.close()


# ── Task 4.1: ImageGenCapability ──────────────────────────────────

import base64


def test_image_gen_build_request():
    from backend.services.multimodal.capability import CapabilityConfig
    from backend.services.multimodal.image_gen import ImageGenCapability
    cap = ImageGenCapability()
    config = CapabilityConfig(base_url="https://api.example.com", api_key="sk-test", model="dall-e-3")
    req = cap.build_request(config, prompt="a cute cat", size="1024x1024", quality="standard")
    assert req.url == "https://api.example.com/images/generations"
    assert req.body["model"] == "dall-e-3"
    assert req.body["prompt"] == "a cute cat"
    assert req.body["response_format"] == "b64_json"
    assert req.timeout == 120.0


def test_image_gen_parse_response_b64(tmp_path, monkeypatch):
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.image_gen import ImageGenCapability
    from backend.services.multimodal.media_store import MediaKind, MediaStore

    cap = ImageGenCapability()
    monkeypatch.setattr("backend.services.multimodal.image_gen.MediaStore",
                        lambda: MediaStore(root=tmp_path))
    png_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    b64_data = base64.b64encode(png_bytes).decode()
    resp = AIHttpResponse(
        status_code=200,
        content=b'{}',
        json={"data": [{"b64_json": b64_data, "revised_prompt": "a cute cat photo"}]},
        content_type="application/json",
    )
    refs = cap.parse_response(resp, prompt="a cute cat")
    assert len(refs) == 1
    assert refs[0].kind == MediaKind.IMAGE
    assert refs[0].source == "image_gen"
    assert refs[0].metadata["prompt"] == "a cute cat"


def test_image_gen_parse_response_error():
    from backend.services.multimodal.capability import AIHttpResponse
    from backend.services.multimodal.image_gen import ImageGenCapability
    cap = ImageGenCapability()
    resp = AIHttpResponse(status_code=400, content=b'bad request')
    with pytest.raises(ValueError, match="400"):
        cap.parse_response(resp)
