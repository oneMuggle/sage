"""R151 — OpenRouter 数据源映射单元测试。

覆盖：model_id 拆分、per-token → per-million 价格换算（免费/未知/
负值/非法区分）、map_openrouter 的类型守卫与字段映射。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.model_catalog.schemas import CandidateModel
from backend.model_catalog.sources import (
    _price_per_million,
    _split_model_id,
    map_openrouter,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _split_model_id
# ---------------------------------------------------------------------------


def test_split_model_id_with_slash():
    key = _split_model_id("openai/gpt-4o")
    assert key.provider == "openai"
    assert key.model_id == "gpt-4o"


def test_split_model_id_without_slash_defaults_provider():
    key = _split_model_id("gpt-4o")
    assert key.provider == "openrouter"
    assert key.model_id == "gpt-4o"


def test_split_model_id_multi_slash_takes_first_provider():
    key = _split_model_id("a/b/c")
    assert key.provider == "a"
    assert key.model_id == "b/c"


def test_split_model_id_empty_slug_falls_back():
    key = _split_model_id("openai/")
    assert key.provider == "openai"  # provider 段存在即用
    assert key.model_id == "openai/"  # slug 为空 → 回退整个 raw_id


# ---------------------------------------------------------------------------
# _price_per_million
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, True, False, "", "  ", "not-a-number", "-0.5"])
def test_price_invalid_inputs_return_none(raw):
    assert _price_per_million(raw) is None


def test_price_zero_means_free():
    assert _price_per_million("0") == Decimal(0)


def test_price_numeric_passthrough_scaled():
    assert _price_per_million("0.0000015") == Decimal("0.0000015") * 1_000_000
    assert _price_per_million(0.5) == Decimal("0.5") * 1_000_000


# ---------------------------------------------------------------------------
# map_openrouter
# ---------------------------------------------------------------------------


def _openrouter_payload(models):
    return {"data": models}


def test_map_openrouter_full_fields():
    data = _openrouter_payload(
        [
            {
                "id": "openai/gpt-4o",
                "context_length": 128000,
                "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            }
        ]
    )
    records = map_openrouter(data)
    assert len(records) == 1
    rec = records[0]
    assert rec.model_key.provider == "openai"
    assert rec.model_key.model_id == "gpt-4o"
    assert rec.native == 128000
    assert rec.price.input_per_million == Decimal("0.0000025") * 1_000_000
    assert rec.price.output_per_million == Decimal("0.00001") * 1_000_000
    assert rec.source == "openrouter"
    assert rec.source_updated_at.endswith("Z")
    assert rec.pricing_scope == "openrouter"


def test_map_openrouter_non_positive_context_length_nulls_native():
    records = map_openrouter(_openrouter_payload([{"id": "a/b", "context_length": 0}]))
    assert records[0].native is None
    records = map_openrouter(_openrouter_payload([{"id": "a/b", "context_length": -5}]))
    assert records[0].native is None


def test_map_openrouter_missing_id_skipped():
    records = map_openrouter(_openrouter_payload([{"context_length": 5}, {"id": ""}, {"id": "  "}]))
    assert records == []


def test_map_openrouter_non_dict_items_skipped():
    records = map_openrouter(_openrouter_payload(["junk", 42, {"id": "ok"}]))
    assert [r.model_key.model_id for r in records] == ["ok"]


def test_map_openrouter_non_dict_pricing_yields_unknown_prices():
    records = map_openrouter(_openrouter_payload([{"id": "x/y", "pricing": "oops"}]))
    assert records[0].price.input_per_million is None
    assert records[0].price.output_per_million is None


@pytest.mark.parametrize("bad", [None, "string", 42])
def test_map_openrouter_rejects_non_dict_data(bad):
    with pytest.raises(TypeError, match="must be a dict"):
        map_openrouter(bad)


def test_map_openrouter_rejects_non_list_data():
    with pytest.raises(TypeError, match="must be a list"):
        map_openrouter({"data": {"id": "x"}})


def test_map_returns_candidate_models():
    records = map_openrouter(_openrouter_payload([{"id": "x/y"}]))
    assert all(isinstance(r, CandidateModel) for r in records)
