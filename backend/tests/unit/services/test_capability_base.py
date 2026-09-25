"""R131 — AICapability 模板方法基类单元测试。

覆盖：枚举与数据类契约（frozen/缺省值）、load_config 的 settings 解析
矩阵（空 settings/无 selection/缺 endpointId/命中端点/模型回退/未命中）、
execute 模板方法的请求实参透传与 JSON/非 JSON 分派（fake AsyncClient）。
"""

from __future__ import annotations

import dataclasses

import httpx
import pytest

from backend.services.multimodal.capability import (
    AICapability,
    AIHttpRequest,
    AIHttpResponse,
    CapabilityConfig,
    CapabilityKind,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 数据类契约
# ---------------------------------------------------------------------------


def test_capability_kind_values():
    assert CapabilityKind.TTS.value == "tts"
    assert CapabilityKind.ASR.value == "asr"
    assert CapabilityKind.IMAGE_GEN.value == "image_gen"


def test_capability_config_frozen():
    config = CapabilityConfig(base_url="https://x", api_key="k", model="m")
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.base_url = "https://y"  # type: ignore[misc]


def test_http_request_defaults():
    req = AIHttpRequest(url="https://x")
    assert req.method == "POST"
    assert req.timeout == 60.0
    assert req.headers == {}
    assert req.body is None
    assert req.data is None
    assert req.files is None


def test_http_response_defaults():
    resp = AIHttpResponse(status_code=200, content=b"")
    assert resp.json is None
    assert resp.content_type == ""


# ---------------------------------------------------------------------------
# load_config 解析矩阵
# ---------------------------------------------------------------------------


def _install_settings(monkeypatch, raw):
    from backend.data import settings_repo

    class _FakeSettingsRepo:
        def get_json(self, key):
            assert key == "app_settings"
            return raw

    monkeypatch.setattr(settings_repo, "SettingsRepository", _FakeSettingsRepo)


def test_load_config_empty_settings_returns_none(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    _install_settings(monkeypatch, None)
    assert TTSCapability().load_config() is None


def test_load_config_no_selections_returns_none(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    _install_settings(monkeypatch, {"endpoints": []})
    assert TTSCapability().load_config() is None


def test_load_config_selection_without_endpoint_id(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    _install_settings(
        monkeypatch,
        {"modelSelections": {"ttsModel": {"endpointId": "", "modelId": "m"}}},
    )
    assert TTSCapability().load_config() is None


def test_load_config_matching_endpoint(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    _install_settings(
        monkeypatch,
        {
            "modelSelections": {"ttsModel": {"endpointId": "ep1", "modelId": "tts-1"}},
            "endpoints": [
                {"id": "ep1", "baseUrl": "https://api.example.com/v1/", "apiKey": "sk"}
            ],
        },
    )
    config = TTSCapability().load_config()
    assert config.base_url == "https://api.example.com/v1"  # 尾斜杠剥离
    assert config.api_key == "sk"
    assert config.model == "tts-1"  # selection 的 modelId 优先


def test_load_config_model_falls_back_to_endpoint_model(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    _install_settings(
        monkeypatch,
        {
            "modelSelections": {"ttsModel": {"endpointId": "ep1"}},
            "endpoints": [{"id": "ep1", "baseUrl": "https://x/", "modelId": "default-tts"}],
        },
    )
    config = TTSCapability().load_config()
    assert config.model == "default-tts"
    assert config.api_key == ""  # 无 apiKey → 空串


def test_load_config_endpoint_not_found_returns_none(monkeypatch):
    from backend.services.multimodal.tts import TTSCapability

    _install_settings(
        monkeypatch,
        {
            "modelSelections": {"ttsModel": {"endpointId": "ghost"}},
            "endpoints": [{"id": "ep1", "baseUrl": "https://x"}],
        },
    )
    assert TTSCapability().load_config() is None


# ---------------------------------------------------------------------------
# execute 模板方法
# ---------------------------------------------------------------------------


class _MiniCapability(AICapability):
    """具体能力替身：记录 build/parse 实参，实现两个抽象方法。"""

    kind = CapabilityKind.TTS
    settings_slot = "ttsModel"

    def __init__(self):
        self.build_kwargs = None
        self.parse_kwargs = None
        self.parse_response_arg = None

    def build_request(self, config, **kwargs):
        self.build_kwargs = kwargs
        return AIHttpRequest(
            url=f"{config.base_url}/audio/speech",
            headers={"Authorization": "Bearer k"},
            body={"input": kwargs.get("text")},
            timeout=120.0,
        )

    def parse_response(self, response, **kwargs):
        self.parse_response_arg = response
        self.parse_kwargs = kwargs
        return "parsed"


class _FakeAsyncClient:
    response = None
    init_kwargs = {}
    request_kwargs = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, **kwargs):
        _FakeAsyncClient.request_kwargs = kwargs
        return _FakeAsyncClient.response


@pytest.fixture()
def mini_capability(monkeypatch):
    from backend.services.multimodal import capability as cap_mod

    _FakeAsyncClient.response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"ok": True},
        request=httpx.Request("POST", "https://x"),
    )
    monkeypatch.setattr(cap_mod.httpx, "AsyncClient", _FakeAsyncClient)
    return _MiniCapability()


@pytest.mark.asyncio()
async def test_execute_passes_request_fields_to_transport(mini_capability, monkeypatch):
    from backend.services.multimodal.capability import CapabilityConfig

    config = CapabilityConfig(base_url="https://x", api_key="k", model="m")
    await mini_capability.execute(config, text="hello")
    sent = _FakeAsyncClient.request_kwargs
    assert sent["url"] == "https://x/audio/speech"
    assert sent["method"] == "POST"
    assert sent["headers"] == {"Authorization": "Bearer k"}
    assert sent["json"] == {"input": "hello"}
    assert sent["timeout"] == 120.0


@pytest.mark.asyncio()
async def test_execute_json_response_parsed(mini_capability):
    from backend.services.multimodal.capability import CapabilityConfig

    config = CapabilityConfig(base_url="https://x", api_key="k", model="m")
    out = await mini_capability.execute(config, text="hello", extra_flag=True)
    assert out == "parsed"
    resp = mini_capability.parse_response_arg
    assert resp.json == {"ok": True}  # JSON content-type → 已解析
    assert mini_capability.parse_kwargs == {"text": "hello", "extra_flag": True}


@pytest.mark.asyncio()
async def test_execute_non_json_response_json_none(monkeypatch, mini_capability):
    from backend.services.multimodal.capability import CapabilityConfig

    _FakeAsyncClient.response = httpx.Response(
        200,
        headers={"content-type": "audio/mpeg"},
        content=b"\x00\x01",
        request=httpx.Request("POST", "https://x"),
    )
    config = CapabilityConfig(base_url="https://x", api_key="k", model="m")
    await mini_capability.execute(config)
    assert mini_capability.parse_response_arg.json is None
    assert mini_capability.parse_response_arg.content == b"\x00\x01"
