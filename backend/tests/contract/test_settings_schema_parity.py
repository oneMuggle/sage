"""Settings schema parity contract tests.

跨边界契约校验: 后端 canonicalizer 的 ALIASES / LEGAL_*_KEYS 与前端
src/entities/setting/types.ts AppSettings 类型定义一致.

目的: 新增 AppSettings 字段时, 忘记同步 LEGAL_*_KEYS 或 ALIASES 时,
pytest 立刻失败, 防止前后端 drift.

参考:
- src/entities/setting/types.ts: AppSettings / EndpointConfig / ModelSelection
- backend/data/settings_canonicalizer.py: ALIASES / LEGAL_*_KEYS
"""

from __future__ import annotations

import re

import pytest

from backend.data.settings_canonicalizer import (
    ALIASES,
    LEGAL_DISCOVERED_MODEL_KEYS,
    LEGAL_ENDPOINT_KEYS,
    LEGAL_MODEL_SELECTION_KEYS,
    LEGAL_MODEL_SELECTIONS_KEYS,
    LEGAL_TOP_KEYS,
    LEGAL_WIKI_KEYS,
    from_camel,
    to_camel,
)

# 前端 AppSettings 13 顶层字段 (camelCase).
# 修改 src/entities/setting/types.ts:AppSettings 时必须同步 LEGAL_TOP_KEYS.
EXPECTED_TOP_KEYS = frozenset(
    {
        "streaming",
        "autoMemory",
        "confirmDelete",
        "compactMode",
        "endpoints",
        "modelSelections",
        "maxContext",
        "temperature",
        "proxyMode",
        "proxyUrl",
        "tlsVersion",
        "wiki",
        "version",
    }
)


def test_legal_top_keys_matches_appsettings_interface() -> None:
    """LEGAL_TOP_KEYS 必须与 AppSettings 13 顶层字段 1:1 对齐."""
    assert LEGAL_TOP_KEYS == EXPECTED_TOP_KEYS


def test_legal_endpoint_keys_is_stable() -> None:
    """LEGAL_ENDPOINT_KEYS 是 EndpointConfig 6 字段."""
    assert (
        frozenset(
            {
                "id",
                "name",
                "baseUrl",
                "apiKey",
                "discoveredModels",
                "lastDiscoveredAt",
            }
        )
        == LEGAL_ENDPOINT_KEYS
    )


def test_legal_model_selection_keys_is_stable() -> None:
    """LEGAL_MODEL_SELECTION_KEYS 是 ModelSelection 2 字段."""
    assert frozenset({"endpointId", "modelId"}) == LEGAL_MODEL_SELECTION_KEYS


def test_legal_discovered_model_keys_is_stable() -> None:
    """LEGAL_DISCOVERED_MODEL_KEYS 是 DiscoveredModel 3 字段."""
    assert (
        frozenset(
            {
                "id",
                "capabilities",
                "endpointId",
            }
        )
        == LEGAL_DISCOVERED_MODEL_KEYS
    )


def test_legal_wiki_keys_is_stable() -> None:
    """LEGAL_WIKI_KEYS 是 WikiSettings 1 字段."""
    assert frozenset({"useFolderPicker"}) == LEGAL_WIKI_KEYS


def test_legal_model_selections_obj_keys_is_stable() -> None:
    """LEGAL_MODEL_SELECTIONS_KEYS 是 modelSelections 对象 3 子字段."""
    assert (
        frozenset(
            {
                "chatModel",
                "visionModel",
                "embeddingModel",
            }
        )
        == LEGAL_MODEL_SELECTIONS_KEYS
    )


def test_aliases_camel_side_subset_of_legal_keys() -> None:
    """ALIASES 翻译后的每个 camelCase 字段必须出现在某个 LEGAL_*_KEYS 里.

    否则 validate_settings_shape 会拒收合法的翻译结果.
    """
    all_legal_camel = (
        LEGAL_TOP_KEYS
        | LEGAL_ENDPOINT_KEYS
        | LEGAL_MODEL_SELECTION_KEYS
        | LEGAL_MODEL_SELECTIONS_KEYS
        | LEGAL_DISCOVERED_MODEL_KEYS
        | LEGAL_WIKI_KEYS
    )
    aliases_camel_side = frozenset(ALIASES.values())
    missing = aliases_camel_side - all_legal_camel
    assert not missing, f"ALIASES camel side not in LEGAL_*_KEYS: {missing}"


def test_aliases_is_bijective() -> None:
    """ALIASES 双向无冲突: 没有 2 个不同 snake 映射到同一 camel."""
    camels = list(ALIASES.values())
    assert len(camels) == len(set(camels))


def test_aliases_snake_side_is_actually_snake_case() -> None:
    """ALIASES key 必须都是 snake_case (含下划线)."""
    for k in ALIASES:
        assert re.match(r"^[a-z][a-z0-9_]*$", k), f"key {k!r} not snake_case"


@pytest.mark.parametrize(
    "snake_key",
    list(ALIASES.keys()),
)
def test_each_alias_translates_to_expected_camel(snake_key: str) -> None:
    """每个 ALIASES 项在 to_camel 后变成对应 camelCase."""
    input_dict = {snake_key: "x"}
    translated = to_camel(input_dict)
    expected_camel = ALIASES[snake_key]
    assert expected_camel in translated, (
        f"to_camel({input_dict}) should produce {expected_camel!r} key, "
        f"got keys: {list(translated.keys())}"
    )


@pytest.mark.parametrize(
    "camel_key",
    list(ALIASES.values()),
)
def test_each_alias_reverse_translates_to_expected_snake(camel_key: str) -> None:
    """每个 ALIASES 反向: from_camel 把 camel 翻回 snake."""
    input_dict = {camel_key: "x"}
    translated = from_camel(input_dict)
    expected_snake = next(k for k, v in ALIASES.items() if v == camel_key)
    assert expected_snake in translated, (
        f"from_camel({input_dict}) should produce {expected_snake!r} key, "
        f"got keys: {list(translated.keys())}"
    )
