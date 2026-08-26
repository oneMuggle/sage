"""settings_canonicalizer 单元测试。

覆盖：
- to_camel 嵌套 dict / list 递归 / 标量通过
- from_camel 反向
- round-trip 一致
- ALIASES 双向一一对应无丢失
- None / empty dict / empty list 通过不爆
- validate_settings_shape 拒绝白名单外 + snake_case 残留
- detect_legacy_snake_pollution nested 检测
"""

from __future__ import annotations

import pytest

from backend.data.settings_canonicalizer import (
    ALIASES,
    detect_legacy_snake_pollution,
    from_camel,
    strip_unknown_fields,
    to_camel,
    validate_endpoint_payload,
    validate_local_model_path,
    validate_protocol,
    validate_settings_payload,
    validate_settings_shape,
)

# --- to_camel ---


def test_to_camel_nested_dict() -> None:
    raw = {"model_selections": {"chat_model": {"endpoint_id": "x"}}}
    assert to_camel(raw) == {"modelSelections": {"chatModel": {"endpointId": "x"}}}


def test_to_camel_endpoints_array_with_discovered_models() -> None:
    raw = {
        "endpoints": [
            {
                "id": "e1",
                "base_url": "u",
                "api_key": "k",
                "discovered_models": [{"id": "m1", "capabilities": ["chat"], "endpoint_id": "e1"}],
                "last_discovered_at": 12345,
            }
        ]
    }
    assert to_camel(raw) == {
        "endpoints": [
            {
                "id": "e1",
                "baseUrl": "u",
                "apiKey": "k",
                "discoveredModels": [{"id": "m1", "capabilities": ["chat"], "endpointId": "e1"}],
                "lastDiscoveredAt": 12345,
            }
        ]
    }


def test_to_camel_passes_through_scalar() -> None:
    assert to_camel(42) == 42
    assert to_camel("hello") == "hello"
    assert to_camel(None) is None


def test_to_camel_empty_collections() -> None:
    assert to_camel([]) == []
    assert to_camel({}) == {}
    assert to_camel({"a": []}) == {"a": []}
    assert to_camel({"a": {}}) == {"a": {}}


def test_to_camel_unknown_keys_kept_as_is() -> None:
    """白名单外的字段(如老 schema 字段 api_base_url)不带 ALIASES 翻译, 但应原样保留"""
    raw = {"api_base_url": "x", "api_key": "k", "model": "m"}
    # 注意: ALIASES 把 api_key 翻成 apiKey, 但 api_base_url / model 不在 ALIASES 中
    assert to_camel(raw) == {"api_base_url": "x", "apiKey": "k", "model": "m"}


# --- from_camel ---


def test_from_camel_round_trip() -> None:
    original = {
        "model_selections": {"chat_model": {"endpoint_id": "x", "model_id": "y"}},
        "endpoints": [
            {
                "id": "e1",
                "base_url": "u",
                "api_key": "k",
                "discovered_models": [{"id": "m1", "endpoint_id": "e1"}],
                "last_discovered_at": 1,
            }
        ],
    }
    round_tripped = from_camel(to_camel(original))
    assert round_tripped["model_selections"] == original["model_selections"]
    assert round_tripped["endpoints"] == original["endpoints"]


# --- ALIASES ---


def test_aliases_is_bijective() -> None:
    """ALIASES 双向一一对应: 没有 2 个不同 snake 映射到同一 camel"""
    camels = list(ALIASES.values())
    assert len(camels) == len(set(camels))


def test_aliases_keys_are_snake_case() -> None:
    """所有 ALIASES key 必须是 snake_case (含下划线)"""
    import re

    for k in ALIASES:
        assert re.match(r"^[a-z][a-z0-9_]*$", k), f"key {k!r} not snake_case"


# --- validate_settings_shape ---


def test_validate_settings_shape_accepts_clean_camel_case() -> None:
    """完整合法的 camelCase AppSettings 不抛错"""
    settings = {
        "streaming": True,
        "autoMemory": True,
        "confirmDelete": True,
        "endpoints": [],
        "modelSelections": {
            "chatModel": {"endpointId": None, "modelId": None},
            "visionModel": {"endpointId": None, "modelId": None},
            "embeddingModel": {"endpointId": None, "modelId": None},
        },
        "maxContext": 4096,
        "temperature": 0.7,
        "wiki": {"useFolderPicker": True},
        "version": "3.0.0",
    }
    validate_settings_shape(settings)


def test_validate_settings_shape_rejects_unknown_top_key() -> None:
    with pytest.raises(ValueError, match=r"unknown top-level field 'foo'"):
        validate_settings_shape({"foo": "bar", "streaming": True})


def test_validate_settings_shape_rejects_unknown_endpoint_key() -> None:
    settings = {"endpoints": [{"id": "x", "baseUrl": "u", "foo": "bar"}]}
    with pytest.raises(ValueError, match=r"unknown endpoint field 'foo'"):
        validate_settings_shape(settings)


def test_validate_settings_shape_rejects_unknown_model_selection_key() -> None:
    settings = {
        "modelSelections": {
            "chatModel": {"endpointId": None, "modelId": None, "junk": 1},
            "visionModel": {"endpointId": None, "modelId": None},
            "embeddingModel": {"endpointId": None, "modelId": None},
        }
    }
    with pytest.raises(ValueError, match=r"unknown model-selection field 'junk'"):
        validate_settings_shape(settings)


def test_validate_settings_shape_strips_snake_residue() -> None:
    """即使翻译后仍有 snake_case 残留 (ALIASES 不覆盖到的字段), 应抛错"""
    settings = {"base_url": "u"}
    with pytest.raises(ValueError, match=r"unknown top-level field 'base_url'"):
        validate_settings_shape(settings)


# --- detect_legacy_snake_pollution ---


def test_detect_returns_empty_for_clean_camel_case() -> None:
    settings = {"endpoints": [{"baseUrl": "u", "apiKey": "k"}]}
    assert detect_legacy_snake_pollution(settings) == []


def test_detect_finds_top_level_snake() -> None:
    settings = {"base_url": "u", "streaming": True}
    paths = detect_legacy_snake_pollution(settings)
    assert "base_url" in paths


def test_detect_finds_nested_snake_in_endpoint() -> None:
    settings = {"endpoints": [{"id": "e1", "base_url": "u", "api_key": "k"}]}
    paths = detect_legacy_snake_pollution(settings)
    assert "endpoints[0].base_url" in paths
    assert "endpoints[0].api_key" in paths


def test_detect_finds_snake_in_discovered_models_array() -> None:
    settings = {"endpoints": [{"discoveredModels": [{"id": "m1", "endpoint_id": "e1"}]}]}
    paths = detect_legacy_snake_pollution(settings)
    assert "endpoints[0].discoveredModels[0].endpoint_id" in paths


def test_detect_finds_snake_in_model_selections() -> None:
    settings = {
        "modelSelections": {
            "chatModel": {"endpoint_id": "x", "model_id": "y"},
            "visionModel": {"endpointId": None, "modelId": None},
            "embeddingModel": {"endpointId": None, "modelId": None},
        }
    }
    paths = detect_legacy_snake_pollution(settings)
    assert "modelSelections.chatModel.endpoint_id" in paths
    assert "modelSelections.chatModel.model_id" in paths


# --- strip_unknown_fields ---


def test_strip_unknown_fields_drops_top_level_residue() -> None:
    """历史残留的顶层字段 (compactMode/proxyMode 等前端已删) 应被剥离"""
    dirty = {
        "streaming": True,
        "compactMode": False,
        "proxyMode": "auto",
        "proxyUrl": "http://x",
        "tlsVersion": "1.2",
        "version": "4.0.0",
    }
    assert strip_unknown_fields(dirty) == {
        "streaming": True,
        "version": "4.0.0",
    }


def test_strip_unknown_fields_drops_endpoint_residue() -> None:
    """endpoints / discoveredModels 层级的未知字段应被剥离"""
    dirty = {
        "endpoints": [
            {
                "id": "e1",
                "name": "A",
                "baseUrl": "https://api.example.com",
                "apiKey": "sk-x",
                "lastDiscoveredAt": 123,
                "category": "primary",  # 残留
                "discoveredModels": [
                    {"id": "m1", "capabilities": ["chat"], "endpointId": "e1", "extra": 1}
                ],
            }
        ]
    }
    cleaned = strip_unknown_fields(dirty)
    assert cleaned["endpoints"][0] == {
        "id": "e1",
        "name": "A",
        "baseUrl": "https://api.example.com",
        "apiKey": "sk-x",
        "lastDiscoveredAt": 123,
        "discoveredModels": [{"id": "m1", "capabilities": ["chat"], "endpointId": "e1"}],
    }


def test_strip_unknown_fields_drops_model_selection_residue() -> None:
    """modelSelections 层级未知 key 与未知 selection 字段应被剥离"""
    dirty = {
        "modelSelections": {
            "chatModel": {"endpointId": "e1", "modelId": "m1", "temperature": 0.7},  # 残留
            "visionModel": {"endpointId": None, "modelId": None},
            "embeddingModel": {"endpointId": None, "modelId": None},
            "rerankModel": {"endpointId": None, "modelId": None},  # 残留
        }
    }
    assert strip_unknown_fields(dirty) == {
        "modelSelections": {
            "chatModel": {"endpointId": "e1", "modelId": "m1"},
            "visionModel": {"endpointId": None, "modelId": None},
            "embeddingModel": {"endpointId": None, "modelId": None},
        }
    }


def test_strip_unknown_fields_drops_wiki_orch_residue() -> None:
    """wiki / orch 层级未知字段应被剥离,合法字段保留 (scratchRoot 是后端配置)"""
    dirty = {
        "wiki": {"useFolderPicker": True, "showSources": False},  # 残留
        "orch": {
            "maxConcurrentSubagents": 4,
            "maxAggregateChars": 120000,
            "scratchRoot": "/tmp/scratch",
            "debugFlag": True,  # 残留
        },
    }
    assert strip_unknown_fields(dirty) == {
        "wiki": {"useFolderPicker": True},
        "orch": {
            "maxConcurrentSubagents": 4,
            "maxAggregateChars": 120000,
            "scratchRoot": "/tmp/scratch",
        },
    }


def test_strip_unknown_fields_keeps_clean_input_unchanged() -> None:
    """全合法输入应原样保留"""
    clean = {
        "streaming": True,
        "endpoints": [{"id": "e1", "baseUrl": "u", "apiKey": "k", "discoveredModels": []}],
        "modelSelections": {
            "chatModel": {"endpointId": "e1", "modelId": "m1"},
            "visionModel": {"endpointId": None, "modelId": None},
            "embeddingModel": {"endpointId": None, "modelId": None},
        },
        "version": "4.0.0",
    }
    assert strip_unknown_fields(clean) == clean


def test_strip_unknown_fields_passes_through_non_dict() -> None:
    """非 dict 输入 (损坏数据) 原样返回,不抛错"""
    assert strip_unknown_fields(None) is None
    assert strip_unknown_fields([]) == []
    assert strip_unknown_fields("junk") == "junk"


def test_strip_unknown_fields_preserves_non_dict_endpoint_item() -> None:
    """类型损坏的端点项 (非 dict) 保留原样,不静默删除 —— 由 validate 报 400 暴露,
    避免无审计的数据丢失。"""
    dirty = {"endpoints": ["corrupted", {"id": "e1", "baseUrl": "u", "junk": 1}]}
    cleaned = strip_unknown_fields(dirty)
    assert cleaned["endpoints"] == ["corrupted", {"id": "e1", "baseUrl": "u"}]


# --- Task 1 新增字段 (timezone / protocol / modelId / localModelPath) ---


def test_to_camel_handles_timezone_alias() -> None:
    """timezone 顶层字段无历史 snake 别名 (默认 Asia/Shanghai 由前端默认值补齐,
    canonicalizer 不翻译 — 顶层 snake 不在 ALIASES → 直接拒收)。"""
    raw = {"timezone": "Asia/Shanghai"}
    # timezone 不在 ALIASES, 直接原样保留 (snake_case 守门交给 validate_settings_shape)
    assert to_camel(raw) == {"timezone": "Asia/Shanghai"}


def test_to_camel_handles_endpoint_protocol_alias() -> None:
    """endpoints[*].protocol 顶层 snake → ALIASES 翻译,无别名则原样保留。"""
    # protocol 不在 ALIASES 里 (camelCase 已是合法形态), 应原样保留
    raw = {"endpoints": [{"id": "e1", "protocol": "openai-compatible"}]}
    assert to_camel(raw) == {"endpoints": [{"id": "e1", "protocol": "openai-compatible"}]}


def test_to_camel_handles_endpoint_model_id_and_local_model_path() -> None:
    """endpoints[*].modelId / localModelPath camelCase 原样保留。"""
    raw = {
        "endpoints": [
            {
                "id": "e1",
                "modelId": "qwen2.5-7b-instruct",
                "localModelPath": "/Users/me/Models/qwen2.5-7b-instruct.gguf",
            }
        ]
    }
    assert to_camel(raw) == {
        "endpoints": [
            {
                "id": "e1",
                "modelId": "qwen2.5-7b-instruct",
                "localModelPath": "/Users/me/Models/qwen2.5-7b-instruct.gguf",
            }
        ]
    }


def test_validate_settings_shape_accepts_new_fields() -> None:
    """含 timezone + endpoints[*].protocol/modelId/localModelPath 的完整 AppSettings 应通过校验。"""
    settings = {
        "streaming": True,
        "autoMemory": True,
        "confirmDelete": True,
        "endpoints": [
            {
                "id": "e1",
                "name": "LM Studio",
                "baseUrl": "http://127.0.0.1:1234/v1",
                "apiKey": "",
                "protocol": "openai-compatible",
                "modelId": "qwen2.5-7b-instruct",
                "localModelPath": None,
                "discoveredModels": [],
                "lastDiscoveredAt": 0,
            }
        ],
        "modelSelections": {
            "chatModel": {"endpointId": "e1", "modelId": "qwen2.5-7b-instruct"},
            "visionModel": {"endpointId": None, "modelId": None},
            "embeddingModel": {"endpointId": None, "modelId": None},
        },
        "maxContext": 4096,
        "temperature": 0.7,
        "timezone": "Asia/Shanghai",
        "wiki": {"useFolderPicker": True},
        "version": "4.0.0",
    }
    validate_settings_shape(settings)


def test_validate_settings_shape_rejects_unknown_protocol_value_silently_via_whitelist() -> None:
    """白名单只锁 key 名, 不锁 value 枚举 (protocol 枚举校验交给 Pydantic 层 hex_routes)。
    canonicalizer 只确保 protocol 字段在 LEGAL_ENDPOINT_KEYS 中, value 任意 str 接受。"""
    settings = {
        "endpoints": [
            {
                "id": "e1",
                "protocol": "future-protocol",  # 白名单不看 value
                "baseUrl": "http://x",
                "apiKey": "",
            }
        ]
    }
    # 不抛错 — protocol 是新白名单 key, value 不在 canonicalizer 校验范围
    validate_settings_shape(settings)


def test_strip_unknown_fields_keeps_new_fields() -> None:
    """新字段 (timezone / modelId / localModelPath) 应原样保留, 不被 strip 误删。"""
    clean = {
        "streaming": True,
        "timezone": "Asia/Shanghai",
        "endpoints": [
            {
                "id": "e1",
                "baseUrl": "http://x",
                "apiKey": "",
                "protocol": "openai-compatible",
                "modelId": "qwen2.5-7b-instruct",
                "localModelPath": "/tmp/qwen.gguf",
                "discoveredModels": [],
                "lastDiscoveredAt": 0,
            }
        ],
    }
    assert strip_unknown_fields(clean) == clean


# === Task 1 round 1 (2026-08-24): protocol / localModelPath value validators ===
# 之前散在 hex_routes / legacy_routes 的 Pydantic ``field_validator`` 装饰器里.
# Pydantic 2 装饰器在 Pydantic 1 / Win7 不可用, 故下沉到 canonicalizer.
# 这些测试覆盖 value 校验 (Pydantic 装饰器已替换, 跑 Pydantic 1/2 同一套函数).


def test_validate_protocol_accepts_legal_values() -> None:
    """4 个合法协议枚举值全部接受."""
    for p in ("openai-compatible", "anthropic", "gemini", "ollama"):
        assert validate_protocol(p) == p  # 原样返回


def test_validate_protocol_passes_through_none_and_empty() -> None:
    """None / 空串视为"未设置", 由 _migrate_default_protocol 兜底补默认值."""
    assert validate_protocol(None) is None
    assert validate_protocol("") == ""


def test_validate_protocol_rejects_non_string() -> None:
    """非 str 类型 (int / dict) → ValueError."""
    with pytest.raises(ValueError, match="protocol must be a string"):
        validate_protocol(123)
    with pytest.raises(ValueError, match="protocol must be a string"):
        validate_protocol({"nested": True})


def test_validate_protocol_rejects_unknown_value() -> None:
    """不在白名单的协议 → ValueError, 提示合法值."""
    with pytest.raises(ValueError, match="invalid protocol"):
        validate_protocol("future-protocol")


def test_validate_local_model_path_accepts_none_and_empty() -> None:
    """None / 空串直接通过."""
    assert validate_local_model_path(None) is None
    assert validate_local_model_path("") == ""


def test_validate_local_model_path_rejects_non_string() -> None:
    """非 str 类型 → ValueError."""
    with pytest.raises(ValueError, match="localModelPath must be a string"):
        validate_local_model_path(123)
    with pytest.raises(ValueError, match="localModelPath must be a string"):
        validate_local_model_path(["array", "is", "not", "allowed"])


def test_validate_local_model_path_win32_rejects_posix_slash() -> None:
    """Task 1 round 1 (2026-08-24): Win32 平台拒绝 POSIX 分隔符 ``/``.

    Win32 路径必须用 ``\\``; 用户的 localModelPath 含 ``/`` 多半是
    LM Studio / Ollama 等跨平台用户把 POSIX 路径直接复制过来, 在 Windows
    上找不到文件. 提早报错比"运行时静默找不到"好.
    """
    # 注入 platform="win32", 避免依赖真实平台.
    with pytest.raises(ValueError, match="Windows path separators"):
        validate_local_model_path("/tmp/qwen.gguf", platform="win32")
    with pytest.raises(ValueError, match="Windows path separators"):
        validate_local_model_path("C:/Users/foo/qwen.gguf", platform="win32")


def test_validate_local_model_path_win32_accepts_backslash() -> None:
    """Win32 平台反斜杠路径正常通过 (UNC / drive letter 等都允许)."""
    assert validate_local_model_path(r"C:\models\qwen.gguf", platform="win32") == r"C:\models\qwen.gguf"
    assert validate_local_model_path(r"\\server\share\model.gguf", platform="win32") == r"\\server\share\model.gguf"


def test_validate_local_model_path_linux_rejects_backslash() -> None:
    """POSIX 平台 (linux / darwin) 拒绝反斜杠 — 历史数据从 Windows 迁过来时常见.

    反斜杠在 POSIX 上不是合法分隔符, 必须用 ``/``. ``bash`` 把 ``\\``
    当字面字符, 路径含 ``\\`` 通常是数据迁移残留.
    """
    with pytest.raises(ValueError, match="POSIX path separators"):
        validate_local_model_path(r"C:\models\qwen.gguf", platform="linux")
    with pytest.raises(ValueError, match="POSIX path separators"):
        validate_local_model_path(r"models\qwen.gguf", platform="darwin")


def test_validate_local_model_path_linux_accepts_forward_slash() -> None:
    """POSIX 平台正斜杠路径正常通过."""
    assert validate_local_model_path("/home/user/qwen.gguf", platform="linux") == "/home/user/qwen.gguf"
    assert validate_local_model_path("./relative/path/model.gguf", platform="linux") == "./relative/path/model.gguf"


def test_validate_endpoint_payload_combined() -> None:
    """单条 endpoint dict: protocol + localModelPath 组合校验.

    传合法 protocol + 合法 path → 通过.
    传合法 protocol + 非法 path → ValueError, message 含 path.
    """
    ep_ok = {"id": "e1", "protocol": "openai-compatible", "localModelPath": "/tmp/q.gguf"}
    assert validate_endpoint_payload(ep_ok, platform="linux") == ep_ok

    ep_bad_path = {"id": "e1", "protocol": "openai-compatible", "localModelPath": r"C:\bad"}
    with pytest.raises(ValueError, match="POSIX path separators"):
        validate_endpoint_payload(ep_bad_path, platform="linux")


def test_validate_endpoint_payload_rejects_non_dict() -> None:
    """endpoint payload 必须是 dict, list/str/number 全部拒绝."""
    with pytest.raises(ValueError, match="endpoint payload must be a dict"):
        validate_endpoint_payload("not-a-dict")
    with pytest.raises(ValueError, match="endpoint payload must be a dict"):
        validate_endpoint_payload([1, 2, 3])


def test_validate_settings_payload_rejects_bad_timezone() -> None:
    """顶层 timezone 非法 → ValueError (handler 翻译 422)."""
    settings = {"timezone": "Not/A/Real/Zone"}
    with pytest.raises(ValueError, match="invalid IANA timezone"):
        validate_settings_payload(settings)


def test_validate_settings_payload_wraps_endpoint_index() -> None:
    """endpoints[i].protocol 非法 → ValueError, message 含 endpoints[i] 索引."""
    settings = {
        "endpoints": [
            {"id": "ok", "protocol": "openai-compatible"},
            {"id": "bad", "protocol": "future-protocol"},  # 第 2 个
        ]
    }
    with pytest.raises(ValueError, match=r"endpoints\[1\]"):
        validate_settings_payload(settings)


def test_validate_settings_payload_non_dict_passes_silently() -> None:
    """非 dict 输入 (None / list / str) 不抛错, 由 validate_settings_shape 兜底."""
    validate_settings_payload(None)
    validate_settings_payload([1, 2, 3])
    validate_settings_payload("not-a-dict")


def test_model_dump_compat_uses_v2_model_dump() -> None:
    """Pydantic 2 path remains preferred when available."""
    from backend.api.settings_models import EndpointPayload, model_dump_compat

    model = EndpointPayload(id="ep-1", protocol="ollama")
    assert model_dump_compat(model, exclude_none=True) == {
        "id": "ep-1",
        "protocol": "ollama",
    }


def test_model_dump_compat_falls_back_to_pydantic_v1_dict() -> None:
    """A v1-shaped model exposing only ``dict`` serializes identically."""
    from backend.api.settings_models import model_dump_compat

    class PydanticV1ShapedModel:
        def dict(self, **kwargs):
            assert kwargs == {"exclude_none": True}
            return {"id": "ep-1"}

    assert model_dump_compat(PydanticV1ShapedModel(), exclude_none=True) == {"id": "ep-1"}


# --- redact_secrets (2026-08-26) ---
#
# OWASP A02:2021 — Cryptographic Failures. GET /settings 必须不返回明文 apiKey.
# 这些单测锁定 redact_secrets + redact_secrets_json 的契约, 防止后续重构回退
# 到"明文返回"的旧实现.


def test_redact_secrets_strips_endpoint_api_key_and_marks_has_api_key():
    from backend.data.settings_canonicalizer import redact_secrets

    settings = {
        "endpoints": [
            {
                "id": "ep-real",
                "baseUrl": "https://api.example.com/v1",
                "apiKey": "sk-test-SECRET-do-not-leak-1f2e3d4c5b6a",
                "protocol": "openai-compatible",
            }
        ]
    }
    out = redact_secrets(settings)
    ep = out["endpoints"][0]
    assert ep["apiKey"] == ""
    assert ep["hasApiKey"] is True
    assert ep["baseUrl"] == "https://api.example.com/v1"
    # immutability check
    assert settings["endpoints"][0]["apiKey"] == "sk-test-SECRET-do-not-leak-1f2e3d4c5b6a"


def test_redact_secrets_empty_api_key_is_false():
    from backend.data.settings_canonicalizer import redact_secrets

    settings = {
        "endpoints": [
            {"id": "ep-empty", "baseUrl": "http://127.0.0.1:1234/v1", "apiKey": ""}
        ]
    }
    out = redact_secrets(settings)
    ep = out["endpoints"][0]
    assert ep["apiKey"] == ""
    assert ep["hasApiKey"] is False


def test_redact_secrets_passthrough_for_none_or_non_dict():
    from backend.data.settings_canonicalizer import redact_secrets

    assert redact_secrets(None) is None
    assert redact_secrets("raw-string") == "raw-string"
    assert redact_secrets([{"endpoints": []}]) == [{"endpoints": []}]
    # 非 dict endpoint 项原样保留
    settings = {"endpoints": ["not-a-dict"]}
    out = redact_secrets(settings)
    assert out["endpoints"] == ["not-a-dict"]


def test_redact_secrets_preserves_other_top_level_keys():
    from backend.data.settings_canonicalizer import redact_secrets

    settings = {
        "endpoints": [{"id": "ep", "apiKey": "secret"}],
        "streaming": True,
        "temperature": 0.7,
        "modelSelections": {"chatModel": {"modelId": "x"}},
    }
    out = redact_secrets(settings)
    assert out["streaming"] is True
    assert out["temperature"] == 0.7
    assert out["modelSelections"]["chatModel"]["modelId"] == "x"


def test_redact_secrets_json_parses_redacts_and_reserializes():
    import json

    from backend.data.settings_canonicalizer import redact_secrets_json

    value = json.dumps(
        {"endpoints": [{"id": "ep", "apiKey": "sk-1234-SECRET"}]}
    )
    out = redact_secrets_json(value)
    assert "sk-1234-SECRET" not in out
    parsed = json.loads(out)
    assert parsed["endpoints"][0]["apiKey"] == ""
    assert parsed["endpoints"][0]["hasApiKey"] is True


def test_redact_secrets_json_passthrough_for_non_string():
    from backend.data.settings_canonicalizer import redact_secrets_json

    assert redact_secrets_json(None) is None
    assert redact_secrets_json(123) == 123
    assert redact_secrets_json("not-valid-json{") == "not-valid-json{"


def test_redact_secrets_json_empty_string_round_trip():
    import json

    from backend.data.settings_canonicalizer import redact_secrets_json

    empty = json.dumps({"endpoints": [{"id": "ep", "apiKey": ""}]})
    out = redact_secrets_json(empty)
    parsed = json.loads(out)
    assert parsed["endpoints"][0]["hasApiKey"] is False


# --- 幂等性 (2026-08-26): plan §8 review HIGH ---
# preference GET round-trip + cache replay 会让 redact_secrets 被多次应用。
# 若 hasApiKey=True 在二次调用时翻成 False, 下游 restoreRedactedApiKeys
# 会拒绝还原, deepMerge remote-wins 用 ``""`` 覆盖本地真实 key → 静默
# 凭据丢失. 锁定这一不变量.


def test_redact_secrets_is_idempotent_for_real_key():
    from backend.data.settings_canonicalizer import redact_secrets

    settings = {
        "endpoints": [
            {"id": "ep", "apiKey": "sk-test-SECRET-do-not-leak-1f2e3d4c5b6a"},
        ]
    }
    once = redact_secrets(settings)
    twice = redact_secrets(once)
    assert twice["endpoints"][0]["apiKey"] == ""
    assert twice["endpoints"][0]["hasApiKey"] is True
    # 二次 = 一次 (除 wrapper ref 外)
    assert twice["endpoints"][0]["hasApiKey"] == once["endpoints"][0]["hasApiKey"]


def test_redact_secrets_is_idempotent_for_empty_key():
    from backend.data.settings_canonicalizer import redact_secrets

    settings = {"endpoints": [{"id": "ep", "apiKey": ""}]}
    once = redact_secrets(settings)
    twice = redact_secrets(once)
    assert twice["endpoints"][0]["apiKey"] == ""
    assert twice["endpoints"][0]["hasApiKey"] is False


def test_redact_secrets_json_is_idempotent():
    """redact_secrets_json 二次调用结果解析后端点字段相同."""
    import json

    from backend.data.settings_canonicalizer import redact_secrets_json

    raw = json.dumps({"endpoints": [{"id": "ep", "apiKey": "sk-test"}]})
    once = redact_secrets_json(raw)
    twice = redact_secrets_json(once)
    parsed = json.loads(twice)
    assert parsed["endpoints"][0]["apiKey"] == ""
    assert parsed["endpoints"][0]["hasApiKey"] is True
