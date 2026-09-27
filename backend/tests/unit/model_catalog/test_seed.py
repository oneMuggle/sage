"""R158 — 内置种子数据解析（_parse_builtin_json）单元测试。

覆盖：根/模型列表类型守卫、非 dict 条目与缺 provider/model_id 跳过、
native 校正、price 透传、pricing_scope 缺省、source_updated_at 三态
（per-model 优先 / generated_at 回退 / 双缺 None）、source 固定 builtin。
"""

from __future__ import annotations

import json

import pytest

from backend.model_catalog.schemas import CandidateModel
from backend.model_catalog.seed import _parse_builtin_json

pytestmark = pytest.mark.unit


def _builtin_json(models, generated_at="2026-01-01T00:00:00Z"):
    return json.dumps({"models": models, "generated_at": generated_at})


def test_root_must_be_dict():
    with pytest.raises(ValueError, match="root must be a dict"):
        _parse_builtin_json(json.dumps([1, 2]))


def test_models_must_be_list():
    with pytest.raises(ValueError, match="must be a list"):
        _parse_builtin_json(json.dumps({"models": {"a": 1}}))


def test_non_dict_model_entries_skipped():
    records = _parse_builtin_json(
        _builtin_json(["junk", 42, {"provider": "p", "model_id": "m"}])
    )
    assert [r.model_key.model_id for r in records] == ["m"]


def test_missing_provider_or_model_id_skipped():
    records = _parse_builtin_json(
        _builtin_json([{"model_id": "x"}, {"provider": "p"}, {"provider": "p", "model_id": "ok"}])
    )
    assert [r.model_key.model_id for r in records] == ["ok"]


def test_native_invalid_becomes_none():
    for bad in ("big", 0, -3):
        records = _parse_builtin_json(
            _builtin_json([{"provider": "p", "model_id": "m", "native": bad}])
        )
        assert records[0].native is None


def test_native_valid_preserved():
    records = _parse_builtin_json(
        _builtin_json([{"provider": "p", "model_id": "m", "native": 128000}])
    )
    assert records[0].native == 128000


def test_price_passthrough():
    records = _parse_builtin_json(
        _builtin_json(
            [
                {
                    "provider": "p",
                    "model_id": "m",
                    "price": {"input_per_million": 1.5, "output_per_million": 2.5},
                }
            ]
        )
    )
    price = records[0].price
    assert price.input_per_million == 1.5
    assert price.output_per_million == 2.5


def test_pricing_scope_defaults_self_hosted():
    records = _parse_builtin_json(
        _builtin_json([{"provider": "p", "model_id": "m", "pricing_scope": "vendor"}])
    )
    assert records[0].pricing_scope == "vendor"
    records_default = _parse_builtin_json(
        _builtin_json([{"provider": "p", "model_id": "m"}])
    )
    assert records_default[0].pricing_scope == "self-hosted"


def test_source_updated_at_prefers_per_model_then_generated_then_none():
    base = [{"provider": "p", "model_id": "m"}]

    with_ts = _parse_builtin_json(
        _builtin_json([{**base[0], "source_updated_at": "2026-05-01T00:00:00Z"}],
                      generated_at="2026-01-01T00:00:00Z")
    )
    assert with_ts[0].source_updated_at == "2026-05-01T00:00:00Z"  # per-model 优先

    with_gen = _parse_builtin_json(_builtin_json(base, generated_at="2026-01-01T00:00:00Z"))
    assert with_gen[0].source_updated_at == "2026-01-01T00:00:00Z"  # 回退顶层

    raw_no_ts = json.dumps({"models": [{"provider": "p", "model_id": "m"}]})
    none_ts = _parse_builtin_json(raw_no_ts)
    assert none_ts[0].source_updated_at is None  # 双缺 → None


def test_source_is_builtin_and_roundtrip():
    records = _parse_builtin_json(
        _builtin_json([{"provider": "p", "model_id": "m", "native": 5}])
    )
    assert records[0].source == "builtin"
    assert isinstance(records[0], CandidateModel)


def test_generated_at_non_string_treated_as_none():
    raw = json.dumps({"models": [{"provider": "p", "model_id": "m"}], "generated_at": 12345})
    records = _parse_builtin_json(raw)
    assert records[0].source_updated_at is None


def test_json_input_roundtrip():
    raw = _builtin_json([{"provider": "p", "model_id": "m"}])
    assert json.loads(raw)["models"][0]["model_id"] == "m"
