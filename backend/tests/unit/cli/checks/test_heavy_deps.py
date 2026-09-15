"""Tests for backend.cli.checks.heavy_deps.HeavyDepsCheck."""
# ruff: noqa: SIM117 — nested with blocks are intentional for clarity in tests
from __future__ import annotations

from unittest import mock

import pytest

from backend.cli.checks.heavy_deps import (
    HEAVY_DEPS,
    HeavyDepsCheck,
    _try_import,
)
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return HeavyDepsCheck()


class TestHeavyDepsMetadata:
    def test_three_known_deps(self):
        """3 个包固定,drift 检测面。"""
        names = {import_name for import_name, _pkg in HEAVY_DEPS}
        assert names == {"hnswlib", "jieba", "sqlite_vec"}


class TestTryImport:
    def test_success(self):
        """任何 stdlib 模块都应能 import。"""
        ok, reason = _try_import("os")
        assert ok is True
        assert reason == "OK"

    def test_not_installed(self):
        ok, reason = _try_import("definitely-not-a-real-pkg-98765")
        assert ok is False
        assert "未安装" in reason

    def test_import_time_error(self):
        """模块存在但 import 时崩(模拟 hnswlib 与 numpy ABI 不兼容的情形)。"""
        with mock.patch(
            "importlib.util.find_spec",
            return_value=mock.Mock(),  # 假装有 spec
        ):
            with mock.patch(
                "backend.cli.checks.heavy_deps.importlib.import_module",
                side_effect=ImportError("numpy ABI mismatch"),
            ):
                ok, reason = _try_import("hnswlib")
        assert ok is False
        assert "ABI" in reason
        assert "ImportError" in reason


class TestHeavyDepsCheck:
    def test_info_when_all_importable(self, check):
        """3 个都 import 成功 → INFO(测试环境:python3 标准库等价物)。"""
        # 用 stdlib 模拟:本次只验"全部成功"的 code path,
        # 我们不替换 HEAVY_DEPS(避免污染全局),而是在 test 里
        # 直接覆盖 _try_import 临时返回 True/False。
        with mock.patch(
            "backend.cli.checks.heavy_deps._try_import",
            return_value=(True, "OK"),
        ):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "3 个重依赖全部可导入" in result.message

    def test_critical_when_all_fail(self, check):
        """3 个都 import 失败 → CRITICAL,启动阻塞(冷启动必查)。"""
        with mock.patch(
            "backend.cli.checks.heavy_deps._try_import",
            return_value=(False, "未安装"),
        ):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "3/3" in result.message
        assert "pip install" in result.fix_hint

    def test_critical_when_one_fails(self, check):
        """1 个失败 → CRITICAL(hnswlib 缺包会直接挂掉所有 embedding 调用)。"""

        def side_effect(name):
            if name == "hnswlib":
                return (False, "未安装(hnswlib)")
            return (True, "OK")

        with mock.patch(
            "backend.cli.checks.heavy_deps._try_import",
            side_effect=side_effect,
        ):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "1/3" in result.message
        assert "hnswlib" in result.message

    def test_check_attributes(self, check):
        assert check.name == "heavy_deps"
        assert isinstance(check.description, str)
        assert "hnswlib" in check.description
