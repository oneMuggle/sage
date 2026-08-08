"""Tests for backend.cli.checks.py_version_match.PyVersionMatchCheck."""
# ruff: noqa: SIM117 — nested with blocks are intentional for clarity in tests
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from backend.cli.checks import py_version_match as pv_mod
from backend.cli.checks.py_version_match import (
    PyVersionMatchCheck,
    _compare,
    _find_python_constraint,
    _parse_environment_yml,
    _parse_python_requirement,
)
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return PyVersionMatchCheck()


def _patch_py_version(major, minor):
    """Patch the check module's view of sys.version_info.

    The real sys.version_info is read-only; this lets the check see whatever
    version we want.
    """
    fake_vi = SimpleNamespace(major=major, minor=minor)
    return mock.patch.object(pv_mod.sys, "version_info", fake_vi)


class TestParsePythonRequirement:
    def test_returns_none_when_file_missing(self, tmp_path):
        assert _parse_python_requirement(tmp_path / "missing.txt") is None

    def test_returns_none_when_no_python_line(self, tmp_path):
        p = tmp_path / "req.txt"
        p.write_text("fastapi==0.109.0\npydantic==2.5.0\n")
        assert _parse_python_requirement(p) is None

    def test_parses_gte(self, tmp_path):
        p = tmp_path / "req.txt"
        p.write_text("python>=3.11\n")
        result = _parse_python_requirement(p)
        assert result == (">=", (3, 11))

    def test_parses_eq(self, tmp_path):
        p = tmp_path / "req.txt"
        p.write_text("python==3.8\n")
        result = _parse_python_requirement(p)
        assert result == ("==", (3, 8))

    def test_parses_legacy_pep440_compatible(self, tmp_path):
        p = tmp_path / "req.txt"
        p.write_text("python~=3.10\n")
        result = _parse_python_requirement(p)
        assert result == ("~=", (3, 10))

    def test_ignores_comments(self, tmp_path):
        p = tmp_path / "req.txt"
        p.write_text("# python>=3.9\nreal-pkg==1.0\n")
        assert _parse_python_requirement(p) is None

    def test_handles_inline_comment(self, tmp_path):
        p = tmp_path / "req.txt"
        p.write_text("python>=3.11 # pinned for sage\n")
        result = _parse_python_requirement(p)
        assert result == (">=", (3, 11))

    def test_returns_none_on_malformed_version(self, tmp_path):
        p = tmp_path / "req.txt"
        p.write_text("python>=abc\n")
        assert _parse_python_requirement(p) is None

    def test_returns_none_on_oserror(self, tmp_path):
        p = mock.Mock()
        p.exists.return_value = True
        p.read_text.side_effect = OSError("perm denied")
        assert _parse_python_requirement(p) is None


class TestParseEnvironmentYml:
    def test_returns_none_when_file_missing(self, tmp_path):
        assert _parse_environment_yml(tmp_path / "missing.yml") is None

    def test_parses_conda_python_eq(self, tmp_path):
        """conda 用单 ``=``：``- python=3.11`` → 等价于 ``==3.11``。"""
        p = tmp_path / "environment.yml"
        p.write_text("name: sage-backend\ndependencies:\n  - python=3.11\n  - pip\n")
        assert _parse_environment_yml(p) == ("==", (3, 11))

    def test_parses_conda_python_double_eq(self, tmp_path):
        p = tmp_path / "environment.yml"
        p.write_text("dependencies:\n  - python==3.8\n")
        assert _parse_environment_yml(p) == ("==", (3, 8))

    def test_returns_none_when_no_python_line(self, tmp_path):
        p = tmp_path / "environment.yml"
        p.write_text("dependencies:\n  - fastapi==0.109.0\n")
        assert _parse_environment_yml(p) is None

    def test_ignores_pip_package_with_python_prefix(self, tmp_path):
        """python-multipart / python-dotenv 等包名不误匹配。"""
        p = tmp_path / "environment.yml"
        p.write_text("dependencies:\n  - python-dotenv==1.0.0\n")
        assert _parse_environment_yml(p) is None

    def test_returns_none_on_oserror(self, tmp_path):
        p = mock.Mock()
        p.exists.return_value = True
        p.read_text.side_effect = OSError("perm denied")
        assert _parse_environment_yml(p) is None


class TestFindPythonConstraint:
    def test_requirements_win_over_environment_yml(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("python>=3.11\n")
        (tmp_path / "environment.yml").write_text("dependencies:\n  - python=3.8\n")
        src, parsed = _find_python_constraint(tmp_path)
        assert src == "requirements.txt"
        assert parsed == (">=", (3, 11))

    def test_falls_back_to_environment_yml(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi==0.109.0\n")
        (tmp_path / "environment.yml").write_text("dependencies:\n  - python=3.8\n")
        src, parsed = _find_python_constraint(tmp_path)
        assert src == "environment.yml"
        assert parsed == ("==", (3, 8))

    def test_none_when_nothing_declared(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi==0.109.0\n")
        (tmp_path / "environment.yml").write_text("name: sage-backend\n")
        assert _find_python_constraint(tmp_path) == (None, None)

    def test_py38_without_constraint_falls_to_requirements(self, tmp_path):
        """requirements-py38.txt 存在但无约束 → 继续尝试 requirements.txt。"""
        (tmp_path / "requirements-py38.txt").write_text("fastapi==0.85.0\n")
        (tmp_path / "requirements.txt").write_text("python>=3.11\n")
        (tmp_path / "environment.yml").write_text("dependencies:\n  - python=3.8\n")
        src, parsed = _find_python_constraint(tmp_path)
        assert src == "requirements.txt"
        assert parsed == (">=", (3, 11))

    def test_py38_with_constraint_wins(self, tmp_path):
        """requirements-py38.txt 带约束 → 优先于 requirements.txt（win7 LTS 路径）。"""
        (tmp_path / "requirements-py38.txt").write_text("python==3.8\n")
        (tmp_path / "requirements.txt").write_text("python>=3.11\n")
        src, parsed = _find_python_constraint(tmp_path)
        assert src == "requirements-py38.txt"
        assert parsed == ("==", (3, 8))


class TestCompare:
    def test_gte(self):
        assert _compare((3, 11), ">=", (3, 11)) is True
        assert _compare((3, 11), ">=", (3, 10)) is True
        assert _compare((3, 10), ">=", (3, 11)) is False

    def test_eq(self):
        assert _compare((3, 8), "==", (3, 8)) is True
        assert _compare((3, 8), "==", (3, 11)) is False

    def test_legacy_pep440(self):
        # ~=3.10 means >=3.10, <4.0
        assert _compare((3, 10), "~=", (3, 10)) is True
        assert _compare((3, 11), "~=", (3, 10)) is True
        assert _compare((4, 0), "~=", (3, 10)) is False
        assert _compare((3, 9), "~=", (3, 10)) is False

    def test_lt_gt(self):
        assert _compare((3, 9), "<", (3, 10)) is True
        assert _compare((3, 11), ">", (3, 10)) is True
        assert _compare((3, 10), "<=", (3, 10)) is True

    def test_neq(self):
        assert _compare((3, 11), "!=", (3, 8)) is True
        assert _compare((3, 8), "!=", (3, 8)) is False

    def test_unknown_op_returns_false(self):
        assert _compare((3, 11), "@@", (3, 11)) is False


class TestPyVersionMatchCheck:
    def test_prefers_requirements_py38(self, check):
        """Win7 LTS: the check must try backend/requirements-py38.txt first,
        not requirements.txt — the py38 variant is the active dependency spec
        on the win7 branch."""
        with mock.patch.object(pv_mod, "_parse_python_requirement") as m:
            m.return_value = None
            check.run()
        first_called_path = m.call_args_list[0].args[0]
        assert first_called_path.name == "requirements-py38.txt"

    def test_info_when_no_python_constraint(self, check):
        with mock.patch.object(pv_mod, "_parse_python_requirement", return_value=None):
            with mock.patch.object(pv_mod, "_parse_environment_yml", return_value=None):
                result = check.run()
        assert result.severity == Severity.INFO
        assert "未声明" in result.message
        assert check.name == "py_version_match"

    def test_uses_environment_yml_fallback(self, check):
        """requirements 无约束时回退 environment.yml 声明。"""
        with mock.patch.object(pv_mod, "_parse_python_requirement", return_value=None):
            with mock.patch.object(pv_mod, "_parse_environment_yml", return_value=("==", (3, 11))):
                with _patch_py_version(3, 11):
                    result = check.run()
        assert result.severity == Severity.INFO
        assert "满足" in result.message
        assert "environment.yml" in result.message

    def test_environment_yml_constraint_mismatch(self, check):
        with mock.patch.object(pv_mod, "_parse_python_requirement", return_value=None):
            with mock.patch.object(pv_mod, "_parse_environment_yml", return_value=("==", (3, 11))):
                with _patch_py_version(3, 8):
                    result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "不满足" in result.message

    def test_info_when_version_matches(self, check):
        with mock.patch.object(pv_mod, "_parse_python_requirement", return_value=(">=", (3, 11))):
            with _patch_py_version(3, 11):
                result = check.run()
        assert result.severity == Severity.INFO
        assert "满足" in result.message

    def test_critical_when_version_too_low(self, check):
        with mock.patch.object(pv_mod, "_parse_python_requirement", return_value=(">=", (3, 11))):
            with _patch_py_version(3, 8):
                result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "不满足" in result.message
        assert "3.8" in result.message
        assert "3.11" in result.message
        assert result.fix_hint is not None

    def test_critical_when_version_too_high(self, check):
        with mock.patch.object(pv_mod, "_parse_python_requirement", return_value=("<=", (3, 8))):
            with _patch_py_version(3, 11):
                result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "不满足" in result.message

    def test_check_attributes(self, check):
        assert check.name == "py_version_match"
        assert isinstance(check.description, str)
        assert check.description
