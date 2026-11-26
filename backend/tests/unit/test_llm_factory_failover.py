"""2026-11-26: 端点链构建测试（优先级排序 / 模型解析 / 冷却后移）。"""

from unittest.mock import patch

from backend.services.endpoint_health import EndpointHealthRegistry
from backend.orchestration.llm_factory import attach_endpoint_chain, build_endpoint_chain


def _ep(eid, priority=None, models=("m1",), model_id=""):
    ep = {
        "id": eid,
        "name": eid,
        "baseUrl": "http://%s" % eid,
        "apiKey": "k",
        "protocol": "openai-compatible",
        "modelId": model_id,
        "discoveredModels": [
            {"id": m, "capabilities": [], "endpointId": eid} for m in models
        ],
    }
    if priority is not None:
        ep["priority"] = priority
    return ep


def test_chain_orders_primary_then_priority():
    eps = [_ep("low", 3), _ep("high", 1), _ep("mid", 2)]
    chain = build_endpoint_chain(
        eps,
        primary_endpoint_id="low",
        primary_model="m1",
        health=EndpointHealthRegistry(),
    )
    assert [hop.endpoint_id for hop in chain] == ["low", "high", "mid"]


def test_same_model_preferred_over_endpoint_default():
    eps = [_ep("a"), _ep("b", models=("m2",), model_id="m2")]
    chain = build_endpoint_chain(
        eps,
        primary_endpoint_id="a",
        primary_model="m1",
        health=EndpointHealthRegistry(),
    )
    assert chain[1].model == "m2"


def test_same_name_model_used_when_available():
    eps = [_ep("a"), _ep("b", models=("m1", "m2"))]
    chain = build_endpoint_chain(
        eps,
        primary_endpoint_id="a",
        primary_model="m1",
        health=EndpointHealthRegistry(),
    )
    assert chain[1].model == "m1"


def test_endpoint_without_model_is_skipped():
    eps = [_ep("a"), _ep("b", models=())]
    chain = build_endpoint_chain(
        eps,
        primary_endpoint_id="a",
        primary_model="m1",
        health=EndpointHealthRegistry(),
    )
    assert [hop.endpoint_id for hop in chain] == ["a"]


def test_cooling_failed_endpoint_moves_last():
    health = EndpointHealthRegistry(threshold=1, cooldown_s=60)
    health.record_failure("high", "timeout")
    eps = [_ep("primary", 2), _ep("high", 1), _ep("third", 3)]
    chain = build_endpoint_chain(
        eps,
        primary_endpoint_id="primary",
        primary_model="m1",
        health=health,
    )
    assert [hop.endpoint_id for hop in chain] == ["primary", "third", "high"]


def test_fallback_model_only_on_primary_hop():
    eps = [_ep("a"), _ep("b")]
    chain = build_endpoint_chain(
        eps,
        primary_endpoint_id="a",
        primary_model="m1",
        fallback_model="mini",
        health=EndpointHealthRegistry(),
    )
    assert chain[0].fallback_model == "mini"
    assert chain[1].fallback_model is None


def test_attach_skips_when_failover_disabled():
    fake_config = type("C", (), {"enabled": False})()
    with patch(
        "backend.services.endpoint_health.load_failover_config", return_value=fake_config
    ):
        cfg = {"endpoint_id": "a", "model": "m1", "base_url": "http://a"}
        assert attach_endpoint_chain(cfg) is cfg


def test_attach_injects_chain_when_enabled():
    fake_config = type("C", (), {"enabled": True})()
    endpoints = [_ep("a"), _ep("b", priority=1)]
    with patch(
        "backend.services.endpoint_health.load_failover_config", return_value=fake_config
    ), patch(
        "backend.services.endpoint_health.get_health_registry",
        return_value=EndpointHealthRegistry(),
    ), patch(
        "backend.data.settings_repo.SettingsRepository"
    ) as repo_cls:
        repo_cls.return_value.get_json.return_value = {"endpoints": endpoints}
        cfg = {
            "endpoint_id": "a",
            "model": "m1",
            "base_url": "http://a",
            "api_key": "k",
        }
        out = attach_endpoint_chain(cfg)
    assert [hop.endpoint_id for hop in out["endpoint_chain"]] == ["a", "b"]
