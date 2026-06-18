"""M6 测试: 确认 Port + Adapter。

覆盖 backend.skills.skill_md.confirm:
- ConfirmationPort Protocol

覆盖 backend.adapters.out.skill_script.*:
- InMemoryAutoConfirmAdapter: 总是返回 True (测试用)
- CliConfirmationAdapter: 通过 HTTP 回调询问前端
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.adapters.out.skill_script.in_memory_auto_confirm import (
    InMemoryAutoConfirmAdapter,
)
from backend.adapters.out.skill_script.cli_confirmation import CliConfirmationAdapter
from backend.skills.skill_md.confirm import ConfirmationPort

pytestmark = pytest.mark.unit


# =====================================================================
# ConfirmationPort Protocol
# =====================================================================


def test_confirmation_port_is_protocol():
    """ConfirmationPort 应该是 Protocol 类型。"""
    assert hasattr(ConfirmationPort, "confirm")
    adapter = InMemoryAutoConfirmAdapter()
    assert hasattr(adapter, "confirm")


# =====================================================================
# InMemoryAutoConfirmAdapter - 测试用
# =====================================================================


def test_in_memory_auto_confirm_returns_true():
    """InMemoryAutoConfirmAdapter.confirm() 总是返回 True。"""
    adapter = InMemoryAutoConfirmAdapter()
    result = asyncio.run(
        adapter.confirm(
            skill_name="test-skill",
            script_path=Path("/tmp/script.py"),
            args=("arg1",),
        )
    )
    assert result is True


def test_in_memory_auto_confirm_with_deny_response():
    """InMemoryAutoConfirmAdapter 可配置为返回 False。"""
    adapter = InMemoryAutoConfirmAdapter(response=False)
    result = asyncio.run(
        adapter.confirm(
            skill_name="test-skill",
            script_path=Path("/tmp/script.py"),
            args=(),
        )
    )
    assert result is False


def test_in_memory_auto_confirm_default_is_true():
    """InMemoryAutoConfirmAdapter 默认 response=True。"""
    adapter = InMemoryAutoConfirmAdapter()
    assert adapter._response is True


def test_in_memory_auto_confirm_callable():
    """InMemoryAutoConfirmAdapter 接受任何参数组合。"""
    adapter = InMemoryAutoConfirmAdapter()
    # 调用时不应抛异常
    result = asyncio.run(
        adapter.confirm(
            skill_name="x",
            script_path=Path("/some/long/path/to/script.py"),
            args=("a", "b", "c"),
        )
    )
    assert result is True


# =====================================================================
# CliConfirmationAdapter - 生产用（HTTP 回调）
# =====================================================================


def test_cli_confirmation_default_construction():
    """CliConfirmationAdapter 默认构造。"""
    adapter = CliConfirmationAdapter()
    assert adapter._timeout_s == 60.0
    assert adapter._callback is None


def test_cli_confirmation_custom_construction():
    """CliConfirmationAdapter 自定义构造。"""
    callback = MagicMock()
    adapter = CliConfirmationAdapter(timeout_s=120.0, callback=callback)
    assert adapter._timeout_s == 120.0
    assert adapter._callback is callback


def test_cli_confirmation_with_callback_returns_true():
    """CliConfirmationAdapter 带 callback 时调用 callback 获取确认。"""
    callback = MagicMock(return_value=True)
    adapter = CliConfirmationAdapter(callback=callback)

    result = asyncio.run(
        adapter.confirm(
            skill_name="test-skill",
            script_path=Path("/tmp/script.py"),
            args=("arg1",),
        )
    )

    assert result is True
    callback.assert_called_once()


def test_cli_confirmation_with_callback_returns_false():
    """CliConfirmationAdapter 带 callback 时调用 callback 获取拒绝。"""
    callback = MagicMock(return_value=False)
    adapter = CliConfirmationAdapter(callback=callback)

    result = asyncio.run(
        adapter.confirm(
            skill_name="test-skill",
            script_path=Path("/tmp/script.py"),
            args=(),
        )
    )

    assert result is False


def test_cli_confirmation_passes_correct_args_to_callback():
    """CliConfirmationAdapter 传递正确的参数给 callback。"""
    callback = MagicMock(return_value=True)
    adapter = CliConfirmationAdapter(callback=callback)

    script = Path("/tmp/test_script.py")
    args = ("arg1", "arg2", "arg3")

    asyncio.run(
        adapter.confirm(skill_name="my-skill", script_path=script, args=args)
    )

    callback.assert_called_once_with(
        skill_name="my-skill", script_path=script, args=args
    )


def test_cli_confirmation_without_callback_defaults_to_true():
    """CliConfirmationAdapter 无 callback 时默认返回 True (向后兼容)。"""
    adapter = CliConfirmationAdapter(callback=None)
    result = asyncio.run(
        adapter.confirm(
            skill_name="x",
            script_path=Path("/tmp/x.py"),
            args=(),
        )
    )
    assert result is True


def test_cli_confirmation_handles_async_callback():
    """CliConfirmationAdapter 支持 async callback (返回 coroutine)。"""
    async_callback = AsyncMock(return_value=True)
    adapter = CliConfirmationAdapter(callback=async_callback)

    result = asyncio.run(
        adapter.confirm(
            skill_name="x",
            script_path=Path("/tmp/x.py"),
            args=(),
        )
    )

    assert result is True
    async_callback.assert_called_once()


def test_cli_confirmation_callback_exception_returns_false():
    """CliConfirmationAdapter callback 抛异常时返回 False (不向上传播)。"""
    callback = MagicMock(side_effect=Exception("callback failed"))
    adapter = CliConfirmationAdapter(callback=callback)

    result = asyncio.run(
        adapter.confirm(
            skill_name="x",
            script_path=Path("/tmp/x.py"),
            args=(),
        )
    )

    assert result is False


def test_cli_confirmation_async_callback_exception_returns_false():
    """CliConfirmationAdapter async callback 抛异常时返回 False。"""
    async_callback = AsyncMock(side_effect=Exception("async callback failed"))
    adapter = CliConfirmationAdapter(callback=async_callback)

    result = asyncio.run(
        adapter.confirm(
            skill_name="x",
            script_path=Path("/tmp/x.py"),
            args=(),
        )
    )

    assert result is False


# =====================================================================
# InMemoryAutoConfirmAdapter - 工厂方法
# =====================================================================


def test_in_memory_auto_confirm_factory():
    """InMemoryAutoConfirmAdapter.auto_approve() 是便捷工厂方法。"""
    adapter = InMemoryAutoConfirmAdapter.auto_approve()
    assert adapter._response is True


def test_in_memory_auto_confirm_factory_deny():
    """InMemoryAutoConfirmAdapter.auto_deny() 是便捷工厂方法。"""
    adapter = InMemoryAutoConfirmAdapter.auto_deny()
    assert adapter._response is False