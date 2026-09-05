"""bash_config 加载器单元测试（PR-2 常量可配置化）。

三态验收（方案 §4）：

- 缺省：无配置 / 空 key → 与硬编码时代的模块常量完全一致；
- 合法：合法 JSON（含部分字段）→ 逐字段生效；
- 越界：类型不对 / 取值越界 / JSON 坏 / 读取失败 → 整体回退默认
  （fail-safe，与 network_config 同口径，不做字段级降级）。

另锁 ``BashConfig`` 默认值与 ``bash_tool`` / ``bash_session`` 模块常量的
一致性 —— 两处漂移时此处先红。
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from backend.tools.bash_config import (
    SETTINGS_KEY_BASH_CONFIG,
    BashConfig,
    load_bash_config,
)
from backend.tools.bash_session import BashSessionRegistry, get_registry
from backend.tools.bash_tool import (
    BASH_DEFAULT_TIMEOUT_SECONDS,
    BASH_MAX_OUTPUT_BYTES,
    BASH_MAX_TIMEOUT_SECONDS,
    BashTool,
)

pytestmark = [pytest.mark.unit]


class _FakeRepo:
    """最小 SettingsRepository 替身：只实现 get()。"""

    def __init__(self, raw):
        self._raw = raw

    def get(self, key):
        assert key == SETTINGS_KEY_BASH_CONFIG
        return self._raw


class _ExplodingRepo:
    """get() 抛异常 —— 模拟 DB 层故障。"""

    def get(self, key):
        raise RuntimeError("db down")


# ---------------------------------------------------------------------------
# 一致性锁：BashConfig 默认值 == 模块常量（硬编码时代的值）
# ---------------------------------------------------------------------------


def test_bash_config_defaults_match_module_constants():
    cfg = BashConfig()
    assert cfg.timeout_default == BASH_DEFAULT_TIMEOUT_SECONDS
    assert cfg.timeout_max == BASH_MAX_TIMEOUT_SECONDS
    assert cfg.output_cap == BASH_MAX_OUTPUT_BYTES
    assert cfg.max_sessions == BashSessionRegistry().max_sessions == 32


# ---------------------------------------------------------------------------
# 缺省态
# ---------------------------------------------------------------------------


def test_missing_key_returns_defaults():
    assert load_bash_config(repo=_FakeRepo(None)) == BashConfig()


def test_empty_string_returns_defaults():
    assert load_bash_config(repo=_FakeRepo("")) == BashConfig()


def test_loader_via_real_settings_repo_empty_db_returns_defaults():
    """真实 SettingsRepository + 空库（conftest tmp DB）→ 默认值。"""
    assert load_bash_config() == BashConfig()


# ---------------------------------------------------------------------------
# 合法态
# ---------------------------------------------------------------------------


def test_valid_full_config_is_parsed():
    raw = json.dumps(
        {
            "timeout_default": 30,
            "timeout_max": 120,
            "output_cap": 4096,
            "max_sessions": 4,
        }
    )
    assert load_bash_config(repo=_FakeRepo(raw)) == BashConfig(
        timeout_default=30.0,
        timeout_max=120.0,
        output_cap=4096,
        max_sessions=4,
    )


def test_partial_config_fills_missing_fields_with_defaults():
    raw = json.dumps({"timeout_default": 45})
    cfg = load_bash_config(repo=_FakeRepo(raw))
    assert cfg.timeout_default == 45.0
    assert cfg.timeout_max == BASH_MAX_TIMEOUT_SECONDS
    assert cfg.output_cap == BASH_MAX_OUTPUT_BYTES
    assert cfg.max_sessions == 32


def test_settings_repo_roundtrip_accepts_bash_config_key():
    """KEYS 白名单已登记 bash_config —— set/get 走通（白名单外会 raise）。"""
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    repo.set(
        SETTINGS_KEY_BASH_CONFIG,
        json.dumps({"timeout_default": 30, "max_sessions": 4}),
    )
    cfg = load_bash_config(repo=repo)
    assert cfg.timeout_default == 30.0
    assert cfg.max_sessions == 4


# ---------------------------------------------------------------------------
# 越界态（全部整体回退默认）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '["a", "b"]',
        '"just a string"',
        '{"timeout_default": "30"}',
        '{"timeout_max": "600"}',
        '{"output_cap": "30k"}',
        '{"max_sessions": 3.5}',
        '{"timeout_default": true}',
        '{"timeout_default": 0}',
        '{"timeout_default": -5}',
        '{"timeout_default": 700, "timeout_max": 600}',
        '{"timeout_max": 0.5}',
        '{"output_cap": 0}',
        '{"output_cap": -1024}',
        '{"max_sessions": 0}',
        '{"max_sessions": -1}',
    ],
)
def test_invalid_config_falls_back_to_defaults(raw):
    assert load_bash_config(repo=_FakeRepo(raw)) == BashConfig()


def test_repo_failure_falls_back_to_defaults():
    assert load_bash_config(repo=_ExplodingRepo()) == BashConfig()


# ---------------------------------------------------------------------------
# 行为接线：BashTool / BashSessionRegistry 读配置
# ---------------------------------------------------------------------------


def test_schema_description_reflects_configured_timeouts():
    tool = BashTool(config=BashConfig(timeout_default=30, timeout_max=120))
    text = tool.schema.description + json.dumps(tool.schema.parameters)
    assert "默认超时 30 秒" in text
    assert "上限 120" in text


def test_default_schema_uses_hardcoded_timeouts():
    """无配置时 schema 文案与硬编码时代一致（120 / 600）。"""
    text = BashTool().schema.description
    assert "默认超时 120 秒" in text
    assert "上限 600" in text


def test_clamp_timeout_uses_configured_max():
    tool = BashTool(config=BashConfig(timeout_default=30, timeout_max=120))
    assert tool._clamp_timeout(10) == 10.0
    assert tool._clamp_timeout(10_000) == 120.0
    assert tool._clamp_timeout(0.1) == 1.0  # 下限仍是模块常量 BASH_MIN


def test_execute_rejects_non_numeric_timeout_before_spawn():
    """timeout 类型校验发生在 spawn 之前 —— 无需子进程即可验证。"""
    result = BashTool().execute(command="echo hi", timeout="120")
    assert result.success is False
    assert "timeout 必须是数字" in (result.error or "")


def test_background_precheck_uses_configured_session_limit(monkeypatch):
    """后台预检查按配置上限拦截（早于 spawn —— stub registry 即可验证）。"""
    import backend.tools.bash_tool as bash_tool_mod

    tool = BashTool(config=BashConfig(max_sessions=1))
    monkeypatch.setattr(
        bash_tool_mod, "get_registry", lambda: SimpleNamespace(count=lambda: 1)
    )
    result = tool.execute(command="echo hi", run_in_background=True)
    assert result.success is False
    assert "上限 1" in (result.error or "")


def test_get_registry_singleton_applies_configured_max(monkeypatch):
    """get_registry() 首次创建时经 load_bash_config 读 max_sessions。

    get_registry 内部是 ``from .bash_config import load_bash_config``（调用时
    解析），所以 monkeypatch 目标是源模块 bash_config，而非 bash_session。
    """
    import backend.tools.bash_config as bash_config_mod
    import backend.tools.bash_session as bash_session_mod

    monkeypatch.setattr(bash_config_mod, "load_bash_config", lambda: BashConfig(max_sessions=7))
    monkeypatch.setattr(bash_session_mod, "_REGISTRY", None)
    registry = get_registry()
    assert registry.max_sessions == 7
    assert get_registry() is registry  # 单例语义保持


@pytest.mark.skipif(
    os.name == "nt",
    reason="spawn_verified 需要 POSIX 进程组（Windows 上按设计拒绝）",
)
def test_registry_register_enforces_configured_limit():
    """registry 自身的 register() 一道也按配置上限拦截（CI/Linux 覆盖）。"""
    from backend.tools.bash_session import SessionLimitExceeded, make_temp_output_file
    from backend.tools.subprocess_util import spawn_verified

    registry = BashSessionRegistry(max_sessions=1)

    def _spawn_and_register(tag: str):
        stdout_path = make_temp_output_file(prefix="sage_cfg_test_")
        stderr_path = make_temp_output_file(prefix="sage_cfg_test_")
        out_handle = open(stdout_path, "wb")  # noqa: SIM115
        err_handle = open(stderr_path, "wb")  # noqa: SIM115
        try:
            verified = spawn_verified(["true"], stdout=out_handle, stderr=err_handle)
        finally:
            out_handle.close()
            err_handle.close()
        return registry.register(verified, tag, stdout_path, stderr_path)

    session = _spawn_and_register("first")
    try:
        with pytest.raises(SessionLimitExceeded, match="上限 1"):
            _spawn_and_register("second")
    finally:
        registry.terminate(session.shell_id, cap=BASH_MAX_OUTPUT_BYTES)
