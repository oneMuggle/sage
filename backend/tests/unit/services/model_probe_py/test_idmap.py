import asyncio

from backend.services.model_probe_py.idmap import (
    isUuid, resolveModelId, refreshModelMap, mapStats, _model_map,
)


def test_is_uuid_recognizes_standard_format():
    assert isUuid("550e8400-e29b-41d4-a716-446655440000")
    assert isUuid("550E8400-E29B-41D4-A716-446655440000")  # uppercase
    assert not isUuid("gpt-4o")
    assert not isUuid("not-a-uuid")
    assert not isUuid("")


def test_resolve_model_id_passthrough_for_non_uuid():
    assert resolveModelId("gpt-4o") == "gpt-4o"
    assert resolveModelId("claude-opus-4-6") == "claude-opus-4-6"


def test_resolve_model_id_uses_injected_map():
    test_map = {
        "550e8400-e29b-41d4-a716-446655440000": "gpt-6-astra-high",
        "660e8400-e29b-41d4-a716-446655440000": "claude-opus-4-6",
    }
    assert resolveModelId("550e8400-e29b-41d4-a716-446655440000", known_map=test_map) == "gpt-6-astra-high"
    assert resolveModelId("660e8400-e29b-41d4-a716-446655440000", known_map=test_map) == "claude-opus-4-6"
    # UUID not in map: passthrough
    assert resolveModelId("770e8400-e29b-41d4-a716-446655440000", known_map=test_map) == "770e8400-e29b-41d4-a716-446655440000"
    # Non-UUID identifier: passthrough regardless of map
    assert resolveModelId("gpt-4o", known_map=test_map) == "gpt-4o"


def test_refresh_model_map_calls_fetcher():
    async def fake_fetcher():
        return {"uuid-xxxx": "gpt-5-turbo"}
    asyncio.run(refreshModelMap(fetcher=fake_fetcher))
    # map should now contain the entry
    assert _model_map.get("uuid-xxxx") == "gpt-5-turbo"


def test_map_stats_returns_loaded_count():
    stats = mapStats()
    assert "loaded" in stats
    assert isinstance(stats["loaded"], int)
