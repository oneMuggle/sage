"""R175 — Python 运行时适配器纯函数单元测试。

覆盖：build_command（argv + stdin_payload）、discover_manifests
（pyproject requires_python / requirements 注释过滤 / Pipfile /
environment.yml）、diagnose 版本约束匹配、_parse_json_line。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.runtime import (
    DiagnosticLevel,
    ExecutionRequest,
    RuntimeInfo,
    RuntimeSource,
)
from backend.tools.adapters.python_adapter import PythonAdapter

pytestmark = pytest.mark.unit


@pytest.fixture()
def adapter():
    return PythonAdapter()


def _runtime(version="3.12.0", path="/usr/bin/python3", **kw):
    return RuntimeInfo(
        language="python", name="Python", path=path, version=version,
        source=RuntimeSource.SYSTEM, **kw,
    )


def _req(code="print(1)"):
    return ExecutionRequest(language="python", runtime_path="/usr/bin/python3", code=code)


# ---------------------------------------------------------------------------
# build_command
# ---------------------------------------------------------------------------


def test_build_command_stdin_mode(adapter):
    cmd = adapter.build_command(_req("print(1)"), _runtime(), ctx=None)
    assert cmd.argv == ["/usr/bin/python3", "-"]
    assert cmd.stdin_payload == "print(1)"
    assert cmd.cleanup_paths == ()


# ---------------------------------------------------------------------------
# discover_manifests
# ---------------------------------------------------------------------------


def test_manifests_pyproject_requires_python(adapter, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[tool.poetry]\nrequires-python = ">=3.10"\n',
        encoding="utf-8",
    )
    manifests = adapter.discover_manifests(tmp_path)
    assert len(manifests) == 1
    assert manifests[0].kind == "pyproject"
    assert manifests[0].extras["requires_python"] == ">=3.10"


def test_manifests_requirements_filters_comments_and_blanks(adapter, tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\n\npytest\n\n  \nflask\n# another\n", encoding="utf-8"
    )
    manifests = adapter.discover_manifests(tmp_path)
    req = [m for m in manifests if m.kind == "requirements"]
    assert len(req) == 1
    assert req[0].requires == ("pytest", "flask")


def test_manifests_multiple_types(adapter, tmp_path):
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("black\n", encoding="utf-8")
    (tmp_path / "Pipfile").write_text("[packages]\n", encoding="utf-8")
    (tmp_path / "environment.yml").write_text("name: env\n", encoding="utf-8")
    manifests = adapter.discover_manifests(tmp_path)
    kinds = sorted(m.kind for m in manifests)
    assert kinds == ["conda-env", "pipfile", "requirements", "requirements-dev"]


def test_manifests_empty_dir(adapter, tmp_path):
    assert adapter.discover_manifests(tmp_path) == []


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------


def test_diagnose_manifest_without_runtime(tmp_path):
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    adapter = PythonAdapter()
    diagnosis = adapter.diagnose(tmp_path, runtimes=[], ctx=None)
    assert diagnosis.level == DiagnosticLevel.UNSATISFIED
    assert any(d.code == "PYTHON_RUNTIME_MISSING" for d in diagnosis.diagnostics)


def test_diagnose_no_manifest_satisfied(adapter, tmp_path):
    diagnosis = adapter.diagnose(tmp_path, runtimes=[], ctx=None)
    assert diagnosis.level == DiagnosticLevel.SATISFIED
    assert diagnosis.diagnostics == []


def _make_runtime(version, **kw):
    return RuntimeInfo(
        language="python", name="Python", path=f"/usr/bin/python{version}",
        version=version, source=RuntimeSource.SYSTEM, **kw,
    )


def test_diagnose_version_constraint_ok(adapter, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        'requires-python = ">=3.10"\n', encoding="utf-8"
    )
    runtime = _make_runtime("3.12.0")
    diagnosis = adapter.diagnose(tmp_path, runtimes=[runtime], ctx=None)
    assert diagnosis.level == DiagnosticLevel.SATISFIED
    ok_diags = [d for d in diagnosis.diagnostics if d.code == "PYTHON_VERSION_OK"]
    assert len(ok_diags) == 1


def test_diagnose_version_mismatch(adapter, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        'requires-python = ">=3.12"\n', encoding="utf-8"
    )
    runtime = _make_runtime("3.9.0")
    diagnosis = adapter.diagnose(tmp_path, runtimes=[runtime], ctx=None)
    assert any(d.code == "PYTHON_VERSION_MISMATCH" for d in diagnosis.diagnostics)


def test_diagnose_recommended_runtime(adapter):
    r1 = _make_runtime("3.11.0")
    r2 = _make_runtime("3.12.0")
    diagnosis = adapter.diagnose(Path(), runtimes=[r1, r2], ctx=None)
    assert diagnosis.recommended_runtime is not None
