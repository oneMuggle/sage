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
