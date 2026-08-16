"""Tests for backend.cli.checks.frontend_dist.FrontendDistCheck.

策略:用 SAGE_DIST_DIR / SAGE_DIST_ELECTRON_DIR env override,把 dist 探测路径
切到 tmp_path,以便灵活构造"存在/缺失/过小"等场景。
"""
# ruff: noqa: SIM117 — nested with blocks are intentional for clarity in tests
from __future__ import annotations

import os
from unittest import mock

import pytest

from backend.cli.checks.frontend_dist import (
    MIN_INDEX_BYTES,
    FrontendDistCheck,
    _resolve_dist_paths,
)
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return FrontendDistCheck()


class TestResolveDistPaths:
    def test_env_takes_precedence(self, tmp_path):
        with mock.patch.dict(
            os.environ,
            {
                "SAGE_DIST_DIR": str(tmp_path / "d"),
                "SAGE_DIST_ELECTRON_DIR": str(tmp_path / "de"),
            },
        ):
            idx, main = _resolve_dist_paths()
        assert idx == (tmp_path / "d" / "index.html").resolve()
        assert main == (tmp_path / "de" / "electron" / "main.js").resolve()

    def test_default_uses_cwd(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            idx, main = _resolve_dist_paths()
        # 默认为 cwd 下的 dist/ 与 dist-electron/(absolute path 形式)
        assert idx.name == "index.html"
        assert "dist" in str(idx)
        assert main.name == "main.js"
        assert "dist-electron" in str(main)


class TestFrontendDistCheck:
    def test_info_when_neither_exists(self, check, tmp_path):
        """dev 模式:dist/ 与 dist-electron/ 都不存在 → INFO(纯源码)"""
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        with mock.patch.dict(
            os.environ,
            {
                "SAGE_DIST_DIR": str(empty_root / "dist"),
                "SAGE_DIST_ELECTRON_DIR": str(empty_root / "dist-electron"),
            },
        ):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "未检测到" in result.message

    def test_critical_when_electron_build_but_no_dist(self, check, tmp_path):
        """dist-electron/ 已构建但 dist/ 缺失(打包半完成)→ CRITICAL,启动阻塞"""
        electron_root = tmp_path / "dist-electron" / "electron"
        electron_root.mkdir(parents=True)
        (electron_root / "main.js").write_bytes(b"console.log('e')")
        # dist/ 不创建
        with mock.patch.dict(
            os.environ,
            {
                "SAGE_DIST_DIR": str(tmp_path / "dist"),
                "SAGE_DIST_ELECTRON_DIR": str(tmp_path / "dist-electron"),
            },
        ):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "dist-electron/ 已构建" in result.message
        assert "npm run build" in result.fix_hint

    def test_warn_when_index_too_small(self, check, tmp_path):
        """dist/index.html 异常小(< 100 字节)→ WARN(可能是构建失败残留)"""
        dist_root = tmp_path / "dist"
        dist_root.mkdir()
        (dist_root / "index.html").write_bytes(b"<html/>")  # 7 字节
        with mock.patch.dict(
            os.environ,
            {"SAGE_DIST_DIR": str(dist_root), "SAGE_DIST_ELECTRON_DIR": str(tmp_path / "nope")},
        ):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "异常小" in result.message
        assert "7" in result.message

    def test_info_when_index_normal(self, check, tmp_path):
        """dist/index.html 大小正常(> MIN_INDEX_BYTES)→ INFO"""
        dist_root = tmp_path / "dist"
        dist_root.mkdir()
        (dist_root / "index.html").write_bytes(b"x" * 2000)
        with mock.patch.dict(
            os.environ,
            {"SAGE_DIST_DIR": str(dist_root), "SAGE_DIST_ELECTRON_DIR": str(tmp_path / "nope")},
        ):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "正常" in result.message
        assert "2000" in result.message

    def test_min_index_bytes_threshold(self):
        """100 字节阈值常量(防构建空产物通过)。"""
        assert MIN_INDEX_BYTES == 100

    def test_check_attributes(self, check):
        assert check.name == "frontend_dist"
        assert isinstance(check.description, str)
        assert check.description
