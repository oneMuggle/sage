"""``/api/v1/runtime/*`` 路由契约测试。

覆盖:

- 3 端点 200 路径: probe / diagnose / exec 走 mock chat_service.tools.execute
- 503 路径: chat_service 未注入、工具未注册
- 工具结果透传: ToolResult 字段 (success / output / error / metadata) 一一映射
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pytest
import pytest_asyncio

from backend.main import app

pytestmark = pytest.mark.unit


@dataclass
class _FakeSpec:
    name: str


@dataclass
class _FakeResult:
    success: bool
    output: Any = None
    error: str | None = None
    metadata: Dict[str, Any] | None = None


class _FakeTools:
    def __init__(self, *, specs: List[_FakeSpec] | None = None):
        self._specs = specs if specs is not None else [
            _FakeSpec("runtime_probe"),
            _FakeSpec("project_diagnose"),
            _FakeSpec("runtime_exec"),
        ]
        self.calls: List[tuple[str, Dict[str, Any]]] = []
        # tool name -> _FakeResult
        self.results: Dict[str, _FakeResult] = {
            "runtime_probe": _FakeResult(
                success=True,
                output={
                    "runtimes": [],
                    "recommended": None,
                    "errors": [],
                },
            ),
            "project_diagnose": _FakeResult(
                success=True,
                output={
                    "project_type": "unknown",
                    "required_languages": [],
                    "diagnostics": [],
                    "satisfied": True,
                },
            ),
            "runtime_exec": _FakeResult(
                success=True,
                output={
                    "exit_code": 0,
                    "stdout": "hi",
                    "stderr": "",
                    "duration_seconds": 0.1,
                },
            ),
        }

    def list_tools(self) -> List[_FakeSpec]:
        return list(self._specs)

    async def execute(self, name: str, args: Dict[str, Any]) -> _FakeResult:
        self.calls.append((name, args))
        return self.results[name]


class _FakeChatService:
    def __init__(self, tools: _FakeTools | None = None):
        self.tools = tools or _FakeTools()


@pytest_asyncio.fixture
async def chat_service_injected():
    """注入 mock chat_service 到 app.state,测试后清理。"""
    service = _FakeChatService()
    app.state.chat_service = service
    yield service
    # teardown — 避免污染其他测试文件
    if hasattr(app.state, "chat_service"):
        delattr(app.state, "chat_service")


# --- 200 路径 ---


@pytest.mark.asyncio()
async def test_probe_returns_tool_result(client, chat_service_injected):
    resp = await client.post("/api/v1/runtime/probe", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "runtimes" in body["output"]
    # dispatch 实际调用了 runtime_probe
    assert chat_service_injected.tools.calls[-1][0] == "runtime_probe"


@pytest.mark.asyncio()
async def test_diagnose_returns_tool_result(client, chat_service_injected):
    resp = await client.post("/api/v1/runtime/diagnose", json={"project_root": "/tmp/x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "project_type" in body["output"]
    name, args = chat_service_injected.tools.calls[-1]
    assert name == "project_diagnose"
    assert args["project_root"] == "/tmp/x"


@pytest.mark.asyncio()
async def test_exec_forwards_args_and_result(client, chat_service_injected):
    payload = {
        "language": "python",
        "runtime_path": "/usr/bin/python3",
        "code": "print(1)",
        "timeout": 30,
    }
    resp = await client.post("/api/v1/runtime/exec", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["output"]["stdout"] == "hi"
    name, args = chat_service_injected.tools.calls[-1]
    assert name == "runtime_exec"
    assert args["language"] == "python"
    assert args["runtime_path"] == "/usr/bin/python3"
    assert args["code"] == "print(1)"
    assert args["timeout"] == 30


@pytest.mark.asyncio()
async def test_exec_without_workspace_root_omits_key(client, chat_service_injected):
    """workspace_root 为 None 时不写入 args (与 probe 同语义)。"""
    payload = {
        "language": "python",
        "runtime_path": "/usr/bin/python3",
        "code": "print(1)",
    }
    resp = await client.post("/api/v1/runtime/exec", json=payload)
    assert resp.status_code == 200
    _, args = chat_service_injected.tools.calls[-1]
    assert "workspace_root" not in args


# --- 503 路径 ---


@pytest.mark.asyncio()
async def test_probe_503_when_chat_service_missing(client):
    if hasattr(app.state, "chat_service"):
        delattr(app.state, "chat_service")
    resp = await client.post("/api/v1/runtime/probe", json={})
    assert resp.status_code == 503
    assert "chat_service" in resp.json()["detail"]


@pytest.mark.asyncio()
async def test_probe_503_when_tool_unregistered(client):
    """tools 列表里缺 runtime_probe -> 503。"""
    service = _FakeChatService(tools=_FakeTools(specs=[]))
    app.state.chat_service = service
    try:
        resp = await client.post("/api/v1/runtime/probe", json={})
        assert resp.status_code == 503
        assert "runtime_probe" in resp.json()["detail"]
    finally:
        delattr(app.state, "chat_service")


# --- ToolResult 字段映射 ---


@pytest.mark.asyncio()
async def test_dispatch_maps_error_and_metadata(client, chat_service_injected):
    chat_service_injected.tools.results["runtime_probe"] = _FakeResult(
        success=False,
        error="boom",
        metadata={"traced": True},
    )
    resp = await client.post("/api/v1/runtime/probe", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["error"] == "boom"
    assert body["metadata"] == {"traced": True}
