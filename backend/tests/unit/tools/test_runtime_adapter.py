"""R163 — RuntimeAdapter 注册中心 + 运行时来源分类单元测试。

覆盖：注册表（大小写归一、重复拒绝、排序、all）、模块级单例、
classify_python_source 的 conda/venv/project/system 路径特征推断。
"""

from __future__ import annotations

import pytest

from backend.domain.runtime import RuntimeSource
from backend.tools.runtime_adapter import (
    AdapterRegistry,
    CommandRequest,
    SafeRunResult,
    classify_python_source,
    registry,
)

pytestmark = pytest.mark.unit


class _FakeAdapter:
    language = "Python"

    def discover(self, request, ctx):
        return []

    def inspect(self, runtime, ctx):
        return runtime

    def build_command(self, request, runtime, ctx):
        raise NotImplementedError

    def diagnose(self, project_root, runtimes, ctx):
        raise NotImplementedError

    def discover_manifests(self, project_root):
        return []


# ---------------------------------------------------------------------------
# AdapterRegistry
# ---------------------------------------------------------------------------


def test_register_then_get_case_insensitive():
    reg = AdapterRegistry()
    adapter = _FakeAdapter()
    reg.register(adapter)  # language = "Python"
    assert reg.get("python") is adapter  # 小写归一命中
    assert reg.get("PYTHON") is adapter


def test_duplicate_registration_rejected():
    reg = AdapterRegistry()
    reg.register(_FakeAdapter())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_FakeAdapter())


def test_get_unregistered_returns_none():
    assert AdapterRegistry().get("ghost") is None


def test_languages_sorted():
    reg = AdapterRegistry()
    a = _FakeAdapter()
    reg.register(a)
    b = _FakeAdapter()
    b.language = "javascript"
    reg.register(b)
    z = _FakeAdapter()
    z.language = "Zig"
    reg.register(z)
    assert reg.languages() == ["javascript", "python", "zig"]


def test_all_returns_list_of_adapters():
    reg = AdapterRegistry()
    a1 = _FakeAdapter()
    reg.register(a1)
    adapters = list(reg.all())
    assert adapters == [a1]


def test_module_level_registry_is_usable():
    # 模块级单例独立于测试本地实例
    assert registry.get("definitely-not-registered") is None


# ---------------------------------------------------------------------------
# classify_python_source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/opt/anaconda3/bin/python", "/usr/local/miniconda/envs/x/python", "/conda/bin/python"],
)
def test_conda_paths(path):
    assert classify_python_source(path, "/proj") == RuntimeSource.CONDA


@pytest.mark.parametrize(
    "path",
    [
        "/home/u/.venv/bin/python",
        "/home/u/proj/venv/bin/python",
        "/x/y/venv/bin/python3",
    ],
)
def test_venv_paths(path):
    assert classify_python_source(path, "/proj") == RuntimeSource.VENV


def test_project_prefix_matches():
    assert classify_python_source("/proj/.tools/python", "/proj") == RuntimeSource.PROJECT


def test_system_fallback():
    assert classify_python_source("/usr/bin/python3", "/proj") == RuntimeSource.SYSTEM


def test_classification_case_insensitive():
    assert classify_python_source("/OPT/ANACONDA3/python", "/proj") == RuntimeSource.CONDA


# ---------------------------------------------------------------------------
# 数据类缺省
# ---------------------------------------------------------------------------


def test_command_request_defaults():
    req = CommandRequest(argv=["python", "-c", "1"])
    assert req.stdin_payload is None
    assert req.env is None
    assert req.cleanup_paths == ()


def test_safe_run_result_defaults():
    result = SafeRunResult(exit_code=0, stdout="o", stderr="", duration_seconds=0.1)
    assert result.timed_out is False
    assert result.output_truncated is False
    assert result.error is None
