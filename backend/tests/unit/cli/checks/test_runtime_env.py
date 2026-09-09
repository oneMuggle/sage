"""Tests for backend.cli.checks.runtime_env.RuntimeEnvCheck."""
from __future__ import annotations

import os
import subprocess
import sys
from unittest import mock

import pytest

from backend.cli.checks.runtime_env import RuntimeEnvCheck
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return RuntimeEnvCheck()


def _patch_packaged_env(value):
    """Set or unset SAGE_IS_PACKAGED in os.environ for the test scope."""
    if value is None:
        return mock.patch.dict(os.environ, {}, clear=False)
    return mock.patch.dict(os.environ, {"SAGE_IS_PACKAGED": value}, clear=False)


def _patch_executable(fake_path):
    return mock.patch.object(sys, "executable", fake_path)


class TestRuntimeEnvPackagedSkip:
    """SAGE_IS_PACKAGED=1 short-circuits runtime_env to a sys.executable
    health check, bypassing RuntimeProbeTool's PATH scan (which would
    miss the bundled Python on packaged Win7 because it's not in PATH).

    Regression: pre-alpha17, packaged Win7 reported CRITICAL because
    runtime_probe scanned PATH and counted zero Python interpreters; the
    actual bundled interpreter at <resources>\\python\\python.exe was
    invisible to it.
    """

    def test_packaged_python_runs_returns_info(self, check):
        """Bundled Python can run --version → INFO with sys.executable path."""
        fake_exe = r"C:\Program Files\Sage\resources\python\python.exe"
        fake_result = subprocess.CompletedProcess(
            args=[fake_exe, "--version"], returncode=0, stdout=b"Python 3.8.10", stderr=b""
        )
        with _patch_executable(fake_exe), _patch_packaged_env("1"), mock.patch(
            "backend.cli.checks.runtime_env.subprocess.run", return_value=fake_result
        ) as mock_run:
            result = check.run()
        assert result.severity == Severity.INFO
        assert "packaged" in result.message
        assert fake_exe in result.message
        called_argv = mock_run.call_args.args[0]
        assert called_argv[0] == fake_exe
        assert called_argv[1] == "--version"

    def test_packaged_python_returns_nonzero_is_critical(self, check):
        """Bundled Python exists but --version fails (corrupted install)
        → CRITICAL with reinstall hint.
        """
        fake_exe = r"C:\Program Files\Sage\resources\python\python.exe"
        fake_result = subprocess.CompletedProcess(
            args=[fake_exe, "--version"], returncode=1, stdout=b"", stderr=b"trace..."
        )
        with _patch_executable(fake_exe), _patch_packaged_env("1"), mock.patch(
            "backend.cli.checks.runtime_env.subprocess.run", return_value=fake_result
        ):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert fake_exe in result.message

    def test_packaged_python_subprocess_raises_is_critical(self, check):
        """subprocess.run raises OSError (binary missing on disk) → CRITICAL."""
        fake_exe = r"C:\Program Files\Sage\resources\python\python.exe"
        with _patch_executable(fake_exe), _patch_packaged_env("1"), mock.patch(
            "backend.cli.checks.runtime_env.subprocess.run",
            side_effect=OSError("No such file"),
        ):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert fake_exe in result.message

    def test_packaged_unset_env_falls_through_to_runtime_probe(self, check):
        """Without SAGE_IS_PACKAGED, RuntimeProbeTool is consulted (the
        original behavior). Verify we don't accidentally short-circuit.
        """
        fake_result = mock.MagicMock()
        fake_result.success = True
        fake_result.content = {"runtimes": [{"language": "python"}, {"language": "javascript"}]}
        with _patch_packaged_env(None), mock.patch(
            "backend.cli.checks.runtime_env.RuntimeProbeTool"
        ) as MockProbe:
            MockProbe.return_value.execute.return_value = fake_result
            result = check.run()
        assert result.severity == Severity.INFO
        MockProbe.return_value.execute.assert_called_once()

    def test_packaged_env_value_must_be_exactly_one(self, check):
        """SAGE_IS_PACKAGED=0 / 'false' / 'true' / '' should fall through
        to RuntimeProbeTool (only the canonical '1' triggers the packaged
        branch — anything else is treated as dev mode).
        """
        fake_result = mock.MagicMock()
        fake_result.success = True
        fake_result.content = {"runtimes": [{"language": "python"}, {"language": "javascript"}]}
        for bad_value in ("0", "false", "true", "yes", ""):
            with mock.patch.dict(
                os.environ, {"SAGE_IS_PACKAGED": bad_value}, clear=False
            ), mock.patch(
                "backend.cli.checks.runtime_env.RuntimeProbeTool"
            ) as MockProbe:
                MockProbe.return_value.execute.return_value = fake_result
                result = check.run()
            assert result.severity == Severity.INFO, (
                f"SAGE_IS_PACKAGED={bad_value!r} should not short-circuit; "
                f"got severity={result.severity!r}"
            )
