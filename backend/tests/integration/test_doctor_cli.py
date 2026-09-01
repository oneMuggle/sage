"""Integration tests for the `sage doctor` CLI.

Invokes ``python -m backend.cli.doctor`` as a real subprocess (text and JSON
modes) and asserts the report shape, exit code, and basic invariants. We
deliberately do NOT start a real backend — the checks that talk to a backend
(backend_health) will report WARN, and that's fine for this integration test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

# Project root is three levels up from backend/tests/integration/
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
# Use sys.executable — works in CI (where conda env is activated) and locally.
SAGE_BACKEND_PY = sys.executable


def _run_doctor(*args, timeout=15):
    """Invoke ``python -m backend.cli.doctor`` and capture output."""
    cmd = [SAGE_BACKEND_PY, "-m", "backend.cli.doctor"] + list(args)
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout, check=False,
    )


class TestDoctorCLITextMode:
    def test_exit_code_in_valid_range(self):
        result = _run_doctor()
        assert result.returncode in (0, 1, 2)
        assert result.returncode != -1

    def test_text_output_contains_summary(self):
        result = _run_doctor()
        assert "总计" in result.stdout

    def test_text_output_contains_all_eight_check_names(self):
        result = _run_doctor()
        expected_names = [
            "conda_env",
            "backend_health",
            "sqlite_writable",
            "config_integrity",
            "port_backend",
            "port_frontend",
            "py_version_match",
            "disk_space",
        ]
        for n in expected_names:
            assert n in result.stdout, f"missing check: {n} in stdout"

    def test_text_output_includes_severity_tags(self):
        result = _run_doctor()
        assert any(
            tag in result.stdout
            for tag in ("[CRITICAL]", "[WARN", "[INFO")
        ), "no severity tag found in stdout"

    def test_text_output_summary_counts_match(self):
        result = _run_doctor()
        for line in result.stdout.splitlines():
            if "总计:" in line:
                assert "CRITICAL:" in line
                assert "WARN:" in line
                assert "INFO:" in line
                break
        else:
            pytest.fail("no '总计:' line found in output")


class TestDoctorCLIJsonMode:
    def test_exit_code_in_valid_range(self):
        result = _run_doctor("--json")
        assert result.returncode in (0, 1, 2)

    def test_json_is_valid(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_json_schema_keys(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        for key in ("checks", "summary", "timestamp", "python_version", "platform"):
            assert key in data, f"missing key: {key}"

    def test_json_has_thirteen_checks(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) == 14

    def test_json_check_entry_shape(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        for entry in data["checks"]:
            assert "name" in entry
            assert "severity" in entry
            assert "message" in entry
            assert "fix_hint" in entry
            assert entry["severity"] in ("critical", "warn", "info")

    def test_json_summary_counts_match(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        summary = data["summary"]
        assert summary["critical"] + summary["warn"] + summary["info"] == 14

    def test_json_python_version_format(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        parts = data["python_version"].split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_json_platform_is_lowercase(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        assert data["platform"] in ("linux", "darwin", "windows")

    def test_json_all_check_names_present(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        names = {entry["name"] for entry in data["checks"]}
        expected = {
            "conda_env",
            "backend_health",
            "sqlite_writable",
            "config_integrity",
            "port_backend",
            "port_frontend",
            "py_version_match",
            "disk_space",
            "llm_config",
            "mcp_servers",
            "heavy_deps",
            "log_dir_size",
            "frontend_dist",
            "skills",
        }
        assert expected.issubset(names)


class TestDoctorCLIExitCodes:
    def test_default_exit_code_matches_severity(self):
        result = _run_doctor("--json")
        data = json.loads(result.stdout)
        summary = data["summary"]

        expected_code = 0
        if summary["critical"] > 0:
            expected_code = 2
        elif summary["warn"] > 0:
            expected_code = 1

        assert result.returncode == expected_code

    def test_text_and_json_agree_on_severity_counts(self):
        text_result = _run_doctor()
        json_result = _run_doctor("--json")
        data = json.loads(json_result.stdout)
        assert text_result.returncode == json_result.returncode
        assert "总计:" in text_result.stdout
        assert data["summary"]["critical"] + data["summary"]["warn"] + data["summary"]["info"] == 14


class TestDoctorCLIHelp:
    def test_help_message(self):
        result = subprocess.run(
            [SAGE_BACKEND_PY, "-m", "backend.cli.doctor", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10, check=False,
        )
        assert result.returncode == 0
        assert "Sage" in result.stdout or "doctor" in result.stdout
