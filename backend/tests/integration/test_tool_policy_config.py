"""M2 配置化 — ``ToolPolicy`` 从 ``config.yaml`` 的 ``tools:`` 段加载。

- 主 ``backend/config.yaml`` 含 ``tools:`` 段，且缺省时为 ``ToolPolicy()`` 默认。
- ``load_tool_policy_from_config(path)`` 从 yaml 读取 ``tools:`` 段并构造
  ``ToolPolicy``；字段缺失回退默认；段缺失全默认。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.application.services.tool_config import load_tool_policy_from_config
from backend.domain.tool_policy import ToolPolicy

pytestmark = pytest.mark.integration


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


def test_main_config_yaml_has_tools_section_with_defaults():
    """主 ``config.yaml`` 含 ``tools:`` 段（无字段覆盖时）→ 加载结果 = ToolPolicy() 默认。"""
    policy = load_tool_policy_from_config(CONFIG_PATH)
    assert policy == ToolPolicy()


def test_load_tool_policy_overrides_each_field(tmp_path: Path):
    """临时 yaml 含非默认 ``tools:`` 字段 → 加载结果覆盖对应字段。"""
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        """
tools:
  timeout_seconds: 5.0
  max_output_bytes: 1024
  max_result_items: 10
  max_read_bytes: 4096
  max_tool_calls_per_run: 3
""",
        encoding="utf-8",
    )

    policy = load_tool_policy_from_config(cfg)

    assert policy == ToolPolicy(
        timeout_seconds=5.0,
        max_output_bytes=1024,
        max_result_items=10,
        max_read_bytes=4096,
        max_tool_calls_per_run=3,
    )


def test_load_tool_policy_missing_section_returns_defaults(tmp_path: Path):
    """yaml 无 ``tools:`` 段 → 全默认。"""
    cfg = tmp_path / "c.yaml"
    cfg.write_text("app:\n  name: x\n", encoding="utf-8")

    policy = load_tool_policy_from_config(cfg)

    assert policy == ToolPolicy()


def test_load_tool_policy_partial_fields_fall_back_to_default(tmp_path: Path):
    """yaml ``tools:`` 段只含部分字段 → 缺字段回退默认。"""
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        """
tools:
  timeout_seconds: 1.0
""",
        encoding="utf-8",
    )

    policy = load_tool_policy_from_config(cfg)

    assert policy.timeout_seconds == 1.0
    assert policy.max_output_bytes == 256_000
    assert policy.max_result_items == 200
    assert policy.max_read_bytes == 2_000_000
    assert policy.max_tool_calls_per_run == 25


def test_load_tool_policy_missing_yaml_returns_defaults(tmp_path: Path):
    """yaml 文件不存在 → 全默认（向后兼容，旧部署无 ``tools:`` 段）。"""
    missing = tmp_path / "does_not_exist.yaml"
    policy = load_tool_policy_from_config(missing)
    assert policy == ToolPolicy()
