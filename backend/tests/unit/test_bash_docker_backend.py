"""bash docker 沙箱执行后端测试（Round 13）"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.tools.bash_tool import BashTool

pytestmark = pytest.mark.unit


@pytest.fixture()
def tool():
    cfg = SimpleNamespace(
        timeout_default=30, timeout_max=300, output_cap=30000
    )
    policy = SimpleNamespace(workspace_root=None)
    return BashTool(policy=policy, config=cfg)


SHELL = SimpleNamespace(
    executable="bash", args_prefix=["-c"], kind="bash", is_fallback=False
)


class TestDockerWrap:
    def test_local_default_passthrough(self, monkeypatch):
        monkeypatch.delenv("SAGE_BASH_EXEC_BACKEND", raising=False)
        argv, cwd = BashTool._docker_maybe_wrap("echo hi", "/tmp/w", SHELL)
        assert argv is None
        assert cwd == "/tmp/w"

    def test_unknown_backend_falls_back_local(self, monkeypatch):
        monkeypatch.setenv("SAGE_BASH_EXEC_BACKEND", "podman-unknown")
        argv, cwd = BashTool._docker_maybe_wrap("echo hi", None, SHELL)
        assert argv is None
        assert cwd is None

    def test_docker_wraps_with_workspace_mount(self, monkeypatch):
        monkeypatch.setenv("SAGE_BASH_EXEC_BACKEND", "docker")
        argv, cwd = BashTool._docker_maybe_wrap("echo hi", "/tmp/w", SHELL)
        assert argv is not None
        assert argv[:2] == ["docker", "run"]
        assert "--rm" in argv
        assert "/tmp/w:/workspace" in argv
        assert "/workspace" in argv
        assert argv[-3:] == ["bash", "-c", "echo hi"]
        assert cwd is None  # 容器内路径由 -w 指定

    def test_docker_without_cwd_no_mount(self, monkeypatch):
        monkeypatch.setenv("SAGE_BASH_EXEC_BACKEND", "docker")
        argv, cwd = BashTool._docker_maybe_wrap("echo hi", None, SHELL)
        assert argv is not None
        assert "/workspace" not in argv
        assert cwd is None

    def test_custom_image(self, monkeypatch):
        monkeypatch.setenv("SAGE_BASH_EXEC_BACKEND", "docker")
        monkeypatch.setenv("SAGE_BASH_DOCKER_IMAGE", "sage-sandbox:latest")
        argv, _ = BashTool._docker_maybe_wrap("echo hi", None, SHELL)
        assert "sage-sandbox:latest" in argv


class TestDecorateMarker:
    def test_docker_backend_marker(self, monkeypatch, tool):
        monkeypatch.setenv("SAGE_BASH_EXEC_BACKEND", "docker")
        content = tool._decorate({}, SHELL, None)
        assert content["exec_backend"] == "docker"

    def test_local_backend_no_marker(self, monkeypatch, tool):
        monkeypatch.delenv("SAGE_BASH_EXEC_BACKEND", raising=False)
        content = tool._decorate({}, SHELL, None)
        assert "exec_backend" not in content
