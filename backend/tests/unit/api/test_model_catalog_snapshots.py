"""R121 — model_catalog snapshots 纯函数单元测试。

覆盖：selected_fields 的 price 展开/去重/校验、field_value 双路径、
canonical_json 规范化与 digest 稳定性、merge_fields 的核心合并语义
（选字段更新、None 永不抹值、clear_fields 回滚、before=None 新建、
source_updated_at 三态）、异常类契约、utc_now 格式。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.model_catalog.schemas import CandidateModel
from backend.model_catalog.snapshots import (
    CatalogConflict,
    CatalogNotFoundError,
    canonical_json,
    digest,
    field_value,
    merge_fields,
    selected_fields,
    utc_now,
)

pytestmark = pytest.mark.unit


def _candidate(**overrides) -> CandidateModel:
    base = {
        "model_key": {"provider": "openrouter", "model_id": "gpt-4o"},
        "native": 5,
        "capabilities": {"vision": True},
        "architecture": "dense",
        "quantization": "q4",
        "price": {"input_per_million": "1.5", "output_per_million": "2.5"},
        "source": "probe",
        "source_updated_at": "2026-09-25T00:00:00Z",
        "pricing_scope": "endpoint",
    }
    base.update(overrides)
    return CandidateModel.model_validate(base)


def _merge(before, after, fields, clear_fields=()):
    return merge_fields(before, after, fields, clear_fields)


# ---------------------------------------------------------------------------
# selected_fields / field_value
# ---------------------------------------------------------------------------


def test_selected_fields_expands_price():
    assert selected_fields(["price"]) == [
        "price.input_per_million",
        "price.output_per_million",
    ]


def test_selected_fields_dedupes_and_preserves_order():
    result = selected_fields(
        ["price.input_per_million", "native", "price", "native"]
    )
    # 去重按展开后顺序保留首次出现
    assert result == [
        "price.input_per_million",
        "native",
        "price.output_per_million",
    ]


@pytest.mark.parametrize("fields", [[], ["bogus"], ["native", "bogus"]])
def test_selected_fields_rejects_invalid(fields):
    with pytest.raises(ValueError, match="catalog value fields"):
        selected_fields(fields)


def test_field_value_price_and_plain_paths():
    data = {"native": 5, "price": {"input_per_million": "1.5"}}
    assert field_value(data, "native") == 5
    assert field_value(data, "price.input_per_million") == "1.5"
    assert field_value(data, "price.output_per_million") is None
    assert field_value(data, "architecture") is None
    assert field_value({}, "price.input_per_million") is None


# ---------------------------------------------------------------------------
# canonical_json / digest / utc_now
# ---------------------------------------------------------------------------


def test_canonical_json_sorts_keys_and_keeps_unicode():
    out = canonical_json({"b": 1, "a": "中文"})
    assert out == '{"a":"中文","b":1}'


def test_digest_stable_and_sensitive():
    r1 = _candidate()
    r2 = _candidate(native=9)
    assert digest([r1, r2]) == digest([r1, r2])
    assert digest([r1]) != digest([r2])
    assert len(digest([r1])) == 64


def test_utc_now_format():
    value = utc_now()
    assert value.endswith("Z")
    datetime.fromisoformat(value.replace("Z", "+00:00"))  # 可解析


# ---------------------------------------------------------------------------
# merge_fields
# ---------------------------------------------------------------------------


def test_merge_updates_selected_and_keeps_unselected():
    before = _candidate()
    after = _candidate(native=7, quantization="q8")  # after 带不同的 q
    merged = _merge(before, after, ["native"])
    assert merged.native == 7  # 选中字段更新
    assert merged.quantization == "q4"  # 未选字段不得被 after 串入
    assert merged.price.input_per_million == before.price.input_per_million
    assert isinstance(merged, CandidateModel)


def test_merge_none_value_never_erases():
    before = _candidate()
    after = _candidate(quantization=None)  # 源数据缺失
    merged = _merge(before, after, ["quantization"])
    assert merged.quantization == "q4"


def test_merge_clear_fields_only_applies_to_null_incoming():
    before = _candidate()
    # clear 指令仅在 after 值为 None 时生效：把"缺失"落为 None 而非保留旧值
    after_null = _candidate(quantization=None)
    keep = _merge(before, after_null, ["quantization"])
    assert keep.quantization == "q4"  # 无 clear → 保留旧值
    cleared = _merge(before, after_null, ["quantization"], clear_fields=["quantization"])
    assert cleared.quantization is None  # 有 clear → 显式置空
    # after 值非 None 时 clear 不产生额外效果
    after_set = _candidate(quantization="q8")
    assert _merge(before, after_set, ["quantization"], ["quantization"]).quantization == "q8"


def test_merge_without_before_nulls_unselected_nonprice_fields():
    after = _candidate(native=7)
    merged = _merge(None, after, ["native"])
    assert merged.native == 7
    assert merged.capabilities is None  # 新建时未选字段不继承 after 残值
    assert merged.quantization is None


def test_merge_without_before_price_keeps_only_selected_paths():
    after = _candidate()
    merged = _merge(None, after, ["price.input_per_million"])
    assert str(merged.price.input_per_million) == "1.5"
    assert merged.price.output_per_million is None  # 未选子路径不串入
    assert merged.price.currency == "USD"


def test_merge_source_updated_at_three_states():
    before = _candidate(source_updated_at="2026-01-01T00:00:00Z")
    # 1) fields 非空且 after 带新时间 → 采用 after
    after_new = _candidate(source_updated_at="2026-09-25T12:00:00Z")
    assert _merge(before, after_new, ["native"]).source_updated_at == (
        "2026-09-25T12:00:00Z"
    )
    # 2) after 时间缺失 → 保留旧值
    after_none = _candidate(source_updated_at=None)
    assert _merge(before, after_none, ["native"]).source_updated_at == (
        "2026-01-01T00:00:00Z"
    )
    # 3) clear_fields → 置 None
    assert _merge(before, after_new, ["native"], ["source_updated_at"]).source_updated_at is None


def test_merge_empty_fields_keeps_snapshot_intact():
    before = _candidate()
    after = _candidate(native=99, quantization="q8")
    merged = _merge(before, after, [])
    assert merged == before  # 零字段选择 = 纯快照，after 不得影响


# ---------------------------------------------------------------------------
# 异常类契约 / 边界
# ---------------------------------------------------------------------------


def test_exception_classes_exist_for_api_mapping():
    assert issubclass(CatalogConflict, Exception)
    assert issubclass(CatalogNotFoundError, Exception)


def test_merge_output_is_frozen_value():
    # CatalogValue.frozen 契约：合并结果不可变（快照审计的完整性前提）
    merged = _merge(_candidate(), _candidate(native=7), ["native"])
    with pytest.raises(ValidationError):
        merged.native = 1
