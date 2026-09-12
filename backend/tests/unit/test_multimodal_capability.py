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
