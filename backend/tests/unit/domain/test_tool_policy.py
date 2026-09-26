"""R140 — ToolPolicy（工具执行统一上限）单元测试。

覆盖：七字段默认值、from_config 全覆盖与缺字段回退、frozen 不可变。
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.domain.tool_policy import ToolPolicy

pytestmark = pytest.mark.unit


def test_defaults_match_design():
    policy = ToolPolicy()
    assert policy.timeout_seconds == 30.0
    assert policy.max_output_bytes == 256_000
    assert policy.max_result_items == 200
    assert policy.max_read_bytes == 2_000_000
    assert policy.max_tool_calls_per_run == 25
    assert policy.workspace_root is None
    assert policy.subagent_only is False


def test_from_config_overrides_all_fields():
    policy = ToolPolicy.from_config(
        {
            "timeout_seconds": 60,
            "max_output_bytes": 1024,
            "max_result_items": 10,
            "max_read_bytes": 2048,
            "max_tool_calls_per_run": 5,
            "workspace_root": "C:/ws",
            "subagent_only": True,
        }
    )
    assert policy.timeout_seconds == 60
    assert policy.max_output_bytes == 1024
    assert policy.max_result_items == 10
    assert policy.max_read_bytes == 2048
    assert policy.max_tool_calls_per_run == 5
    assert policy.workspace_root == "C:/ws"
    assert policy.subagent_only is True


def test_from_config_missing_fields_fall_back():
    policy = ToolPolicy.from_config({"timeout_seconds": 5})
    assert policy.timeout_seconds == 5
    assert policy.max_output_bytes == 256_000  # 其余回退默认
    assert policy.max_tool_calls_per_run == 25


def test_from_config_empty_dict_is_defaults():
    policy = ToolPolicy.from_config({})
    assert policy == ToolPolicy()


def test_policy_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ToolPolicy().timeout_seconds = 1  # type: ignore[misc]
