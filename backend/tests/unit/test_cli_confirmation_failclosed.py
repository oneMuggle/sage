"""M3 权限与安全边界 — ``CliConfirmationAdapter`` fail-closed（方案 §3.3）。

- callback 为 ``None`` 时**默认拒绝**（False）；不再默认放行（向后兼容旧假设被打破，
  但这是安全收益，应在初始化路径显式注入自动确认回调）。
- callback 抛异常仍返回 False（既有行为保持）。
- callback 正常返回 bool → 按返回值。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.adapters.out.skill_script.cli_confirmation import CliConfirmationAdapter

pytestmark = pytest.mark.unit


def test_no_callback_returns_false_fail_closed():
    """callback=None 时 confirm() 必须返回 False（fail-closed）。"""
    adapter = CliConfirmationAdapter(callback=None)
    result = asyncio.run(adapter.confirm("skill_x", Path("/tmp/x.sh"), ("arg1",)))
    assert result is False


def test_callback_returning_true_is_honored():
    adapter = CliConfirmationAdapter(callback=lambda **_: True)
    result = asyncio.run(adapter.confirm("skill_x", Path("/tmp/x.sh"), ()))
    assert result is True


def test_callback_returning_false_is_honored():
    adapter = CliConfirmationAdapter(callback=lambda **_: False)
    result = asyncio.run(adapter.confirm("skill_x", Path("/tmp/x.sh"), ()))
    assert result is False


def test_callback_raising_exception_returns_false():
    def bad_cb(**_):
        raise RuntimeError("boom")

    adapter = CliConfirmationAdapter(callback=bad_cb)
    result = asyncio.run(adapter.confirm("skill_x", Path("/tmp/x.sh"), ()))
    assert result is False


def test_async_callback_returning_true_is_honored():
    async def ok(**_):
        return True

    adapter = CliConfirmationAdapter(callback=ok)
    result = asyncio.run(adapter.confirm("skill_x", Path("/tmp/x.sh"), ()))
    assert result is True
