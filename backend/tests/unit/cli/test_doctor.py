"""sage doctor — protocol + main() + exit code + JSON output tests."""
# ruff: noqa: ERA001 — section divider comments (===) are not commented-out code
from __future__ import annotations

import dataclasses
import json

import pytest

from backend.cli.doctor import (
    ALL_CHECKS,
    CheckResult,
    Severity,
    _exit_code,
    _format_json,
    _format_text,
    _run_one,
    _summarize,
    build_parser,
    main,
    register,
    run_doctor,
)

# ============================================================
# Severity / CheckResult / to_dict
# ============================================================


class TestSeverity:
    """Severity enum should be a str-mixed enum whose value is JSON-friendly."""

    def test_severity_values(self):
        assert Severity.CRITICAL.value == "critical"
        assert Severity.WARN.value == "warn"
        assert Severity.INFO.value == "info"

    def test_severity_is_str(self):
        assert json.dumps(Severity.CRITICAL) == '"critical"'
        assert json.dumps(Severity.WARN) == '"warn"'
        assert json.dumps(Severity.INFO) == '"info"'


class TestCheckResult:
    def test_to_dict_with_fix_hint(self):
        result = CheckResult(
            name="foo",
            severity=Severity.WARN,
            message="msg",
            fix_hint="do X",
        )
        d = result.to_dict()
        assert d == {
            "name": "foo",
            "severity": "warn",
            "message": "msg",
            "fix_hint": "do X",
        }

    def test_to_dict_without_fix_hint(self):
        result = CheckResult(name="bar", severity=Severity.INFO, message="ok")
        d = result.to_dict()
        assert d == {
            "name": "bar",
            "severity": "info",
            "message": "ok",
            "fix_hint": None,
        }

    def test_frozen_dataclass(self):
        result = CheckResult(name="x", severity=Severity.INFO, message="m")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.severity = Severity.WARN  # type: ignore[misc]

    def test_severity_is_serializable(self):
        result = CheckResult(name="n", severity=Severity.CRITICAL, message="m")
        encoded = json.dumps(result.to_dict())
        decoded = json.loads(encoded)
        assert decoded["severity"] == "critical"


# ============================================================
# register() decorator
# ============================================================


class TestRegister:
    def test_register_appends_to_all_checks(self):
        before = len(ALL_CHECKS)
        try:

            @register
            class _Dummy:
                name = "test_register_dummy"
                description = "x"

            assert len(ALL_CHECKS) == before + 1
            assert ALL_CHECKS[-1] is _Dummy
        finally:
            if ALL_CHECKS and ALL_CHECKS[-1].__name__ == "_Dummy":
                ALL_CHECKS.pop()

    def test_register_returns_class(self):
        @register
        class _Dummy2:
            name = "test_register_dummy2"
            description = "x"

        try:
            assert _Dummy2.__name__ == "_Dummy2"
        finally:
            if ALL_CHECKS and ALL_CHECKS[-1].__name__ == "_Dummy2":
                ALL_CHECKS.pop()


# ============================================================
# _summarize / _exit_code
# ============================================================


class TestSummarize:
    def test_empty(self):
        assert _summarize([]) == {"critical": 0, "warn": 0, "info": 0}

    def test_counts_each_severity(self):
        results = [
            CheckResult("a", Severity.CRITICAL, "m"),
            CheckResult("b", Severity.WARN, "m"),
            CheckResult("c", Severity.INFO, "m"),
            CheckResult("d", Severity.INFO, "m"),
        ]
        assert _summarize(results) == {"critical": 1, "warn": 1, "info": 2}


class TestExitCode:
    def test_all_info_returns_zero(self):
        results = [
            CheckResult("a", Severity.INFO, "ok"),
            CheckResult("b", Severity.INFO, "ok"),
        ]
        assert _exit_code(results) == 0

    def test_warn_returns_one(self):
        results = [
            CheckResult("a", Severity.INFO, "ok"),
            CheckResult("b", Severity.WARN, "hmm"),
        ]
        assert _exit_code(results) == 1

    def test_critical_returns_two(self):
        results = [
            CheckResult("a", Severity.WARN, "w"),
            CheckResult("b", Severity.CRITICAL, "c"),
        ]
        assert _exit_code(results) == 2

    def test_empty_returns_zero(self):
        assert _exit_code([]) == 0


# ============================================================
# _format_text / _format_json
# ============================================================


class TestFormatText:
    def test_includes_all_results(self):
        results = [
            CheckResult("check_a", Severity.INFO, "all good"),
            CheckResult("check_b", Severity.CRITICAL, "broken"),
        ]
        text = _format_text(results)
        assert "check_a" in text
        assert "check_b" in text
        assert "CRITICAL" in text
        assert "INFO" in text
        assert "总计" in text

    def test_includes_fix_hint_when_present(self):
        results = [
            CheckResult("c", Severity.WARN, "msg", fix_hint="do this"),
        ]
        text = _format_text(results)
        assert "do this" in text
        assert "fix:" in text

    def test_omits_fix_line_when_absent(self):
        results = [CheckResult("c", Severity.INFO, "ok")]
        text = _format_text(results)
        assert "fix:" not in text

    def test_summary_line_counts(self):
        results = [
            CheckResult("a", Severity.CRITICAL, "x"),
            CheckResult("b", Severity.WARN, "x"),
            CheckResult("c", Severity.INFO, "x"),
            CheckResult("d", Severity.INFO, "x"),
        ]
        text = _format_text(results)
        assert "CRITICAL: 1" in text
        assert "WARN: 1" in text
        assert "INFO: 2" in text


class TestFormatJson:
    def test_schema_keys_present(self):
        results = [CheckResult("a", Severity.INFO, "ok")]
        text = _format_json(results)
        data = json.loads(text)
        assert "checks" in data
        assert "summary" in data
        assert "timestamp" in data
        assert "python_version" in data
        assert "platform" in data

    def test_python_version_format(self):
        data = json.loads(_format_json([]))
        parts = data["python_version"].split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_platform_is_lowercase(self):
        data = json.loads(_format_json([]))
        assert data["platform"] in ("linux", "darwin", "windows")

    def test_checks_array_round_trip(self):
        results = [
            CheckResult("a", Severity.INFO, "ok"),
            CheckResult("b", Severity.CRITICAL, "bad", fix_hint="rebuild"),
        ]
        data = json.loads(_format_json(results))
        assert len(data["checks"]) == 2
        assert data["checks"][0]["name"] == "a"
        assert data["checks"][0]["severity"] == "info"
        assert data["checks"][1]["name"] == "b"
        assert data["checks"][1]["severity"] == "critical"
        assert data["checks"][1]["fix_hint"] == "rebuild"

    def test_unicode_safe(self):
        results = [CheckResult("c", Severity.WARN, message="中文消息")]
        data = json.loads(_format_json(results))
        assert data["checks"][0]["message"] == "中文消息"


class TestRunDoctor:
    def test_reports_explicit_runtime_and_package_root(self, tmp_path):
        # Finding #5 (Task 0 review round 1): doctor now performs a real
        # `import backend.main` via the supplied interpreter. Passing a
        # non-existent interpreter path therefore legitimately reports
        # `import_backend=False`. Use sys.executable + the real repo
        # root so the probe actually succeeds and we also exercise the
        # exact backend_command/cwd/env contract that the supervisor uses.
        import sys
        from pathlib import Path

        # `package_root` is the directory that CONTAINS the ``backend/``
        # package directory on disk (the supervisor's `<resourcesPath>`);
        # it is used both as cwd and PYTHONPATH for the probe so
        # ``import backend.main`` resolves to ``package_root/backend/main.py``.
        backend_dir = Path(__file__).resolve().parents[3]   # .../backend
        package_root = backend_dir.parent                  # .../<repo>
        runtime = run_doctor(
            interpreter=sys.executable,
            package_root=package_root,
        )
        assert runtime.interpreter == str(Path(sys.executable).resolve())
        assert runtime.package_root == str(package_root)
        assert runtime.import_backend is True

    def test_propagates_backend_env_to_import_subprocess(self, monkeypatch, tmp_path):
        # Round 2 (fast-follow E): when the supervisor passes its launcher
        # context (SAGE_BACKEND_GENERATION / SAGE_BACKEND_OWNERSHIP_TOKEN /
        # PYTHONPATH) via ``backend_env``, the ``import backend.main`` probe
        # subprocess MUST see those exact keys. Otherwise the probe runs in
        # a stripped env and the doctor verdict diverges from what the
        # supervisor's child backend would actually experience.
        import subprocess
        import sys
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parents[3]
        package_root = backend_dir.parent
        supervisor_env = {
            "SAGE_BACKEND_GENERATION": "7",
            "SAGE_BACKEND_OWNERSHIP_TOKEN": "tok-abc",
            "PYTHONPATH": str(package_root) + ":_sage_core_marker",
            "SAGE_DB_PATH": str(tmp_path / "sage.db"),
        }

        captured: dict = {}

        class _FakeCompletedProcess:
            returncode = 0

        def _fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env")
            captured["timeout"] = kwargs.get("timeout")
            return _FakeCompletedProcess()

        monkeypatch.setattr(subprocess, "run", _fake_run)

        runtime = run_doctor(
            interpreter=sys.executable,
            package_root=package_root,
            backend_env=supervisor_env,
        )
        assert runtime.import_backend is True
        # The probe argv always probes ``import backend.main``; what we
        # care about here is the env contract.
        assert captured["argv"][-2:] == ["-c", "import backend.main"]
        env = captured["env"]
        assert env is not None
        # Supervisor markers must reach the probe verbatim.
        assert env["SAGE_BACKEND_GENERATION"] == "7"
        assert env["SAGE_BACKEND_OWNERSHIP_TOKEN"] == "tok-abc"
        assert env["SAGE_DB_PATH"] == str(tmp_path / "sage.db")
        # Supervisor-provided PYTHONPATH must WIN over the package-root
        # default that ``run_doctor`` builds from ``package_root`` alone.
        assert env["PYTHONPATH"] == supervisor_env["PYTHONPATH"]
        # Probe still inherits PATH/SYSTEMROOT so the bundled interpreter
        # is discoverable.
        assert "PATH" in env
        # Hard 20s cap must be honoured so a broken installer never hangs.
        # (baseline 实测冷启动 import backend.main 约 5-6s, 5s 在冷环境下 flaky.)
        assert captured["timeout"] == 20


# ============================================================
# _run_one: fail-open
# ============================================================


class TestRunOne:
    def test_returns_check_result_on_success(self):
        class _Good:
            name = "good"
            description = "x"

            def run(self):
                return CheckResult(self.name, Severity.INFO, "fine")

        result = _run_one(_Good)
        assert result.severity == Severity.INFO
        assert result.message == "fine"

    def test_fail_open_on_exception(self):
        class _Bad:
            name = "bad"
            description = "x"

            def run(self):
                raise RuntimeError("kaboom")

        result = _run_one(_Bad)
        assert result.severity == Severity.WARN
        assert "RuntimeError" in result.message
        assert "kaboom" in result.message
        assert result.name == "bad"

    def test_uses_class_name_when_no_name_attr(self):
        class _NoName:
            description = "x"

            def run(self):
                raise ValueError("oops")

        result = _run_one(_NoName)
        assert result.name == "_NoName"
        assert result.severity == Severity.WARN


# ============================================================
# build_parser
# ============================================================


class TestBuildParser:
    def test_default_no_args(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.as_json is False

    def test_json_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--json"])
        assert args.as_json is True


# ============================================================
# main() — end-to-end (uses real registered checks)
# ============================================================


class TestMain:
    def test_main_returns_int_in_valid_range(self, capsys):
        code = main([])
        assert code in (0, 1, 2)
        out = capsys.readouterr().out
        assert "总计" in out

    def test_main_with_json(self, capsys):
        code = main(["--json"])
        assert code in (0, 1, 2)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "checks" in data
        assert "summary" in data
        # 2026-09-05: 15→16 (加 network)
        assert len(data["checks"]) == 16

    def test_main_runs_all_sixteen_checks(self, capsys):
        main([])
        out = capsys.readouterr().out
        expected_names = [
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
            # 2026-09-04: 本地开发环境助手 — Python/Node.js 探测
            "runtime_env",
            # 2026-09-05: 网络访问策略（mode / host 白名单 / httpx 依赖）
            "network",
        ]
        for n in expected_names:
            assert n in out, f"missing check: {n}"

    def test_main_exit_code_with_critical_inject(self, capsys):
        from backend.cli import doctor as d

        class _CriticalCheck:
            name = "_test_critical_inject"
            description = "injected"

            def run(self):
                return CheckResult(self.name, Severity.CRITICAL, "injected")

        original = list(d.ALL_CHECKS)
        # Replace ALL_CHECKS to isolate the exit code from real checks
        d.ALL_CHECKS[:] = [_CriticalCheck]
        try:
            code = main([])
            assert code == 2
        finally:
            d.ALL_CHECKS[:] = original

    def test_main_exit_code_with_warn_inject(self, capsys):
        from backend.cli import doctor as d

        class _WarnCheck:
            name = "_test_warn_inject"
            description = "injected"

            def run(self):
                return CheckResult(self.name, Severity.WARN, "w")

        original = list(d.ALL_CHECKS)
        # Isolate to only the injected check
        d.ALL_CHECKS[:] = [_WarnCheck]
        try:
            code = main([])
            assert code == 1
        finally:
            d.ALL_CHECKS[:] = original

    def test_main_fail_open_when_check_raises(self, capsys):
        from backend.cli import doctor as d

        class _ExplodingCheck:
            name = "_test_explode"
            description = "x"

            def run(self):
                raise RuntimeError("intentional")

        original = list(d.ALL_CHECKS)
        d.ALL_CHECKS[:] = [_ExplodingCheck]
        try:
            code = main([])
            # The exploded check is caught -> WARN -> exit code 1
            assert code == 1
            out = capsys.readouterr().out
            assert "_test_explode" in out
        finally:
            d.ALL_CHECKS[:] = original

    def test_main_info_only_returns_zero(self, capsys):
        from backend.cli import doctor as d

        original = list(d.ALL_CHECKS)
        d.ALL_CHECKS[:] = []

        class _InfoCheck:
            name = "_test_info"
            description = "x"

            def run(self):
                return CheckResult(self.name, Severity.INFO, "ok")

        d.ALL_CHECKS.append(_InfoCheck)
        try:
            code = main([])
            assert code == 0
            out = capsys.readouterr().out
            assert "_test_info" in out
        finally:
            d.ALL_CHECKS[:] = original


# ============================================================
# _import_all_checks  # noqa: ERA001 — section dividers, not commented-out code
# ============================================================


class TestImportAllChecks:
    def test_call_does_not_crash(self):
        from backend.cli import doctor as d

        before = len(d.ALL_CHECKS)
        d._import_all_checks()
        # After import, 8 unique classes should be registered
        # 2026-09-05: 15→16 (加 network)
        assert len(d.ALL_CHECKS) >= 16
        # Calling twice doesn't crash (may double-register; that's fine)
        d._import_all_checks()
        assert len(d.ALL_CHECKS) >= before
