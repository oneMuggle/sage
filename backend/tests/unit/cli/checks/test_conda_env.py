"""Tests for backend.cli.checks.conda_env.CondaEnvCheck."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from backend.cli.checks import conda_env as conda_env_mod
from backend.cli.checks.conda_env import CondaEnvCheck
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return CondaEnvCheck()


def _patch_exe(fake_exe_path):
    """Patch sys.executable AND mock Path.resolve() to return the fake path.

    ``Path.resolve()`` follows symlinks, so a non-existent fake_exe_path would
    be resolved to a different path. We bypass resolve by mocking Path.resolve
    for the conda_env module.
    """
    fake_path = Path(fake_exe_path)

    def fake_resolve(self, *args, **kwargs):
        return fake_path

    p_resolve = mock.patch.object(Path, "resolve", fake_resolve)
    p_exe = mock.patch.object(sys, "executable", fake_exe_path)
    return p_exe, p_resolve


def _patch_py_version(major, minor):
    """Patch the check module's view of sys.version_info to (major, minor).

    conda_env uses ``sys.version_info.major`` / ``.minor`` directly. We replace
    ``conda_env.sys.version_info`` with a SimpleNamespace so the check sees
    the version we want without mutating the real read-only attribute.
    """
    fake_vi = SimpleNamespace(major=major, minor=minor)
    return mock.patch.object(conda_env_mod.sys, "version_info", fake_vi)


class _FakeResolvedPath:
    """Minimal stand-in for a resolved ``Path`` with POSIX/Windows ``parts``.

    On a POSIX CI runner ``Path(r"C:\\...")`` keeps backslashes in a single
    part, so Windows paths can't be exercised through the real class. This
    fake provides the two surface areas ``CondaEnvCheck.run()`` touches:
    ``str(path)`` and ``path.parts``.
    """

    def __init__(self, raw: str, parts):
        self._raw = raw
        self.parts = parts

    def __str__(self):
        return self._raw


class TestCondaEnvCheck:
    """CondaEnvCheck: verifies Python interpreter is in a sage conda env."""

    def test_info_when_in_sage_backend(self, check):
        """When sys.executable is under /anaconda3/envs/sage-backend, expect INFO."""
        fake_exe = "/anaconda3/envs/sage-backend/bin/python3.11"
        p_exe, p_resolve = _patch_exe(fake_exe)
        with p_exe, p_resolve, _patch_py_version(3, 11):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "环境正确" in result.message
        assert result.name == "conda_env"

    def test_info_when_in_sage_backend_py38(self, check):
        """py38 path with Py3.8 - happy path. Note: startswith ordering makes
        the py38 branch unreachable in normal flow, but the path that starts
        with sage-backend-py38 still matches the first expected prefix.
        """
        fake_exe = "/anaconda3/envs/sage-backend-py38/bin/python3.8"
        p_exe, p_resolve = _patch_exe(fake_exe)
        with p_exe, p_resolve, _patch_py_version(3, 8):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "3.8" in result.message

    def test_info_when_in_windows_conda_env(self, check):
        """Win7 LTS: Windows conda env path must NOT false-positive CRITICAL.

        The main-branch check hardcodes ``/anaconda3/envs/...`` prefixes, which
        never match ``C:\\Users\\x\\anaconda3\\envs\\sage-backend-py38\\python.exe``.
        The win7 adaptation matches the ``envs/<name>`` path segments instead.
        On a POSIX CI runner ``Path()`` won't split backslash paths, so we mock
        the resolved path's ``parts`` directly.
        """
        fake = _FakeResolvedPath(
            r"C:\Users\SageUser\anaconda3\envs\sage-backend-py38\python.exe",
            ("C:\\", "Users", "SageUser", "anaconda3", "envs", "sage-backend-py38", "python.exe"),
        )
        with mock.patch.object(Path, "resolve", return_value=fake), _patch_py_version(3, 8):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "环境正确" in result.message

    def test_windows_py38_env_with_wrong_version_is_critical(self, check):
        """Win7 LTS: py38 env running Py3.11 -> CRITICAL even on Windows paths."""
        fake = _FakeResolvedPath(
            r"C:\Users\SageUser\anaconda3\envs\sage-backend-py38\python.exe",
            ("C:\\", "Users", "SageUser", "anaconda3", "envs", "sage-backend-py38", "python.exe"),
        )
        with mock.patch.object(Path, "resolve", return_value=fake), _patch_py_version(3, 11):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "py38" in result.message

    def test_critical_when_path_starts_with_py38_prefix_only(self, check):
        """Construct a path that ONLY matches the py38 expected prefix (not
        the plain sage-backend prefix). This requires the second iteration
        of EXPECTED_PATHS to be reached - which means the first must miss.

        After the EXPECTED_PATHS ordering fix (long path first), a path
        matching the py38 prefix will hit the py38 branch, and a non-3.8
        interpreter there returns CRITICAL.
        """
        # py38 prefix matches first (now), and the interpreter is 3.11,
        # so the py38-mismatch branch fires -> CRITICAL
        fake_exe = "/anaconda3/envs/sage-backend-py38/bin/python3.11"
        p_exe, p_resolve = _patch_exe(fake_exe)
        with p_exe, p_resolve, _patch_py_version(3, 11):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "py38" in result.message

    def test_critical_when_not_in_conda_env(self, check):
        """Plain system python -> CRITICAL with fix hint."""
        fake_exe = "/usr/bin/python3"
        p_exe, p_resolve = _patch_exe(fake_exe)
        with p_exe, p_resolve:
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "不在 Sage conda 环境" in result.message
        assert result.fix_hint is not None
        assert "conda activate" in result.fix_hint
        assert "/usr/bin/python3" in result.message

    def test_critical_when_in_other_conda_env(self, check):
        """Path is in some conda env, but not sage-backend -> CRITICAL."""
        fake_exe = "/anaconda3/envs/some-other-env/bin/python"
        p_exe, p_resolve = _patch_exe(fake_exe)
        with p_exe, p_resolve:
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "some-other-env" in result.message

    def test_check_attributes(self, check):
        """Verify the class exposes the required Check protocol attributes."""
        assert check.name == "conda_env"
        assert isinstance(check.description, str)
        assert check.description
