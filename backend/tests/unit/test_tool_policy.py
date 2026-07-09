"""M2 显式限制 — ToolPolicy 域类型单测。

- dataclass 默认值与方案 §3.2 设计一致。
- ``from_config(dict)`` 用 dict 覆盖字段；缺字段回退默认。
- ``from_config({})`` 全默认。
- frozen: 构造后不可改。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from backend.domain.tool_policy import ToolPolicy

pytestmark = pytest.mark.unit


def test_default_values_match_design():
    p = ToolPolicy()
    assert p.timeout_seconds == 30.0
    assert p.max_output_bytes == 256_000
    assert p.max_result_items == 200
    assert p.max_read_bytes == 2_000_000
    assert p.max_tool_calls_per_run == 25


def test_from_config_overrides_each_field():
    cfg = {
        "timeout_seconds": 5.0,
        "max_output_bytes": 1024,
        "max_result_items": 10,
        "max_read_bytes": 4096,
        "max_tool_calls_per_run": 3,
    }
    p = ToolPolicy.from_config(cfg)
    assert p == ToolPolicy(
        timeout_seconds=5.0,
        max_output_bytes=1024,
        max_result_items=10,
        max_read_bytes=4096,
        max_tool_calls_per_run=3,
    )


def test_from_config_missing_fields_fall_back_to_default():
    p = ToolPolicy.from_config({"timeout_seconds": 1.0})
    assert p.timeout_seconds == 1.0
    # 其余字段回退默认
    assert p.max_output_bytes == 256_000
    assert p.max_result_items == 200
    assert p.max_read_bytes == 2_000_000
    assert p.max_tool_calls_per_run == 25


def test_from_config_empty_dict_returns_defaults():
    p = ToolPolicy.from_config({})
    assert p == ToolPolicy()


def test_policy_is_frozen():
    p = ToolPolicy()
    with pytest.raises(FrozenInstanceError):
        p.timeout_seconds = 1.0  # type: ignore[misc]
