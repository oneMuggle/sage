"""R145 — 运行时领域模型（runtime.py）单元测试。

覆盖：三枚举取值、RuntimeCapability/RuntimeInfo 缺省、_runtime_to_dict
全字段形状、Probe/Execution 请求与结果缺省及 to_dict 契约（duration
舍入、command 条件序列化）、ProjectManifest/Diagnostic/
ProjectDiagnosis 嵌套序列化、frozen 不可变。
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.domain.runtime import (
    Diagnostic,
    DiagnosticLevel,
    DiagnosticSeverity,
    ExecutionRequest,
    ExecutionResult,
    ProbeRequest,
    ProbeResult,
    ProjectDiagnosis,
    ProjectManifest,
    RuntimeCapability,
    RuntimeInfo,
    RuntimeSource,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


def test_runtime_source_values():
    assert {s.value for s in RuntimeSource} == {
        "system", "conda", "venv", "project", "toolchain", "unknown",
    }


def test_diagnostic_level_values():
    assert {lv.value for lv in DiagnosticLevel} == {"satisfied", "partial", "unsatisfied"}


def test_diagnostic_severity_values():
    assert {s.value for s in DiagnosticSeverity} == {"info", "warning", "error"}


# ---------------------------------------------------------------------------
# 数据类缺省与 frozen
# ---------------------------------------------------------------------------


def test_runtime_capability_defaults():
    cap = RuntimeCapability()
    assert cap.can_execute is False
    assert cap.can_package_check is False
    assert cap.supports_stdin_source is True
    assert cap.supports_tempfile_source is True
    assert cap.notes == ""


def test_runtime_info_defaults_and_frozen():
    info = RuntimeInfo(language="python", name="py312", path="/usr/bin/python3", version="3.12")
    assert info.source == RuntimeSource.UNKNOWN
    assert info.is_default is False
    assert info.is_compatible is None
    assert info.compatibility_notes == ()
    assert info.capabilities == RuntimeCapability()
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.language = "js"  # type: ignore[misc]


def test_probe_request_defaults():
    req = ProbeRequest()
    assert req.languages == ()
    assert req.include_tools is True
    assert req.target_version is None
    assert req.include_paths == ()


# ---------------------------------------------------------------------------
# to_dict 序列化
# ---------------------------------------------------------------------------


def test_probe_result_to_dict():
    info = RuntimeInfo(language="python", name="py", path="/p", version="3")
    result = ProbeResult(runtimes=[info], recommended="py", errors=("e1",))
    d = result.to_dict()
    assert d["recommended"] == "py"
    assert d["errors"] == ["e1"]
    assert d["runtimes"][0]["language"] == "python"
    assert d["runtimes"][0]["source"] == "unknown"
    assert d["runtimes"][0]["capabilities"]["can_execute"] is False


def test_execution_request_defaults():
    req = ExecutionRequest(language="python", runtime_path="/p", code="print(1)")
    assert req.cwd is None
    assert req.timeout == 60
    assert req.run_in_background is False
    assert req.env_overrides == {}


def test_execution_result_to_dict_rounding_and_command():
    result = ExecutionResult(
        exit_code=0,
        stdout="out",
        stderr="",
        duration_seconds=1.23456,
        command=["python", "-c", "print(1)"],
    )
    d = result.to_dict()
    assert d["duration_seconds"] == 1.2346  # round(4)
    assert d["command"] == ["python", "-c", "print(1)"]
    assert d["timed_out"] is False
    assert d["error"] is None


def test_execution_result_no_command_serializes_none():
    result = ExecutionResult(exit_code=1, stdout="", stderr="err", duration_seconds=0.5)
    assert result.to_dict()["command"] is None


def test_project_manifest_defaults():
    manifest = ProjectManifest(language="python", path=".", kind="requirements")
    assert manifest.requires == ()
    assert manifest.extras == {}


def test_diagnostic_to_dict():
    diag = Diagnostic(
        code="NO_RUNTIME",
        severity=DiagnosticSeverity.ERROR,
        message="未找到 python",
        remediation="安装 python",
    )
    d = diag.to_dict()
    assert d == {
        "code": "NO_RUNTIME",
        "severity": "error",
        "message": "未找到 python",
        "remediation": "安装 python",
        "related_path": None,
    }


def test_project_diagnosis_to_dict_nested():
    diagnosis = ProjectDiagnosis(
        level=DiagnosticLevel.PARTIAL,
        diagnostics=[Diagnostic(code="C1", severity=DiagnosticSeverity.WARNING, message="m")],
        manifests=[ProjectManifest(language="python", path=".", kind="pip")],
        recommended_runtime="py312",
    )
    d = diagnosis.to_dict()
    assert d["level"] == "partial"
    assert d["diagnostics"][0]["severity"] == "warning"
    assert d["manifests"][0]["kind"] == "pip"
    assert d["recommended_runtime"] == "py312"
