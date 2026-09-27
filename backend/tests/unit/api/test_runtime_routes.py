"""R168 — runtime_routes 分派层单元测试。

覆盖：chat_service 缺失 503、工具未注册 503、_dispatch 的
success/output/error/metadata 透传与 fail-open 200 语义、
_dispatch_structured 的 output JSON 反序列化（成功与失败路径）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.runtime_routes import (
    _dispatch,
    _dispatch_structured,
    _get_chat_service,
    _require_tool,
)

pytestmark = pytest.mark.unit


def _tool_result(success=True, output=None, error=None, metadata=None):
    return SimpleNamespace(
        success=success, output=output, error=error, metadata=metadata
    )


class _FakeTools:
    def __init__(self, registered, result):
        self._registered = set(registered)
        self._result = result
        self.execute_calls = []

    def list_tools(self):
        return [SimpleNamespace(name=n) for n in self._registered]

    async def execute(self, tool_name, args):
        self.execute_calls.append((tool_name, args))
        return self._result


def _fake_request(chat_service):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(chat_service=chat_service)))


# ---------------------------------------------------------------------------
# _get_chat_service / _require_tool
# ---------------------------------------------------------------------------


def test_get_chat_service_missing_503():
    with pytest.raises(HTTPException) as excinfo:
        _get_chat_service(_fake_request(None))
    assert excinfo.value.status_code == 503


def test_get_chat_service_present():
    cs = SimpleNamespace()
    assert _get_chat_service(_fake_request(cs)) is cs


def test_require_tool_registered_passes():
    cs = SimpleNamespace(tools=SimpleNamespace(list_tools=lambda: [SimpleNamespace(name="runtime_probe")]))
    _require_tool(cs, "runtime_probe")  # 不抛


def test_require_tool_unregistered_503():
    cs = SimpleNamespace(tools=SimpleNamespace(list_tools=lambda: []))
    with pytest.raises(HTTPException) as excinfo:
        _require_tool(cs, "runtime_probe")
    assert excinfo.value.status_code == 503


# ---------------------------------------------------------------------------
# _dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_dispatch_success_passthrough(monkeypatch):
    cs = SimpleNamespace(
        tools=_FakeTools(["runtime_probe"], _tool_result(True, output={"n": 1}, metadata={"k": "v"}))
    )
    payload = await _dispatch(_fake_request(cs), "runtime_probe", {"languages": ["py"]})
    assert payload["success"] is True
    assert payload["output"] == {"n": 1}
    assert payload["metadata"] == {"k": "v"}
    assert "error" not in payload


@pytest.mark.asyncio()
async def test_dispatch_output_none_omits_key(monkeypatch):
    cs = SimpleNamespace(
        tools=_FakeTools(["runtime_probe"], _tool_result(True, output=None))
    )
    payload = await _dispatch(_fake_request(cs), "runtime_probe", {})
    assert "output" not in payload
    assert payload["success"] is True


@pytest.mark.asyncio()
async def test_dispatch_error_included_still_200(monkeypatch):
    cs = SimpleNamespace(
        tools=_FakeTools(["runtime_exec"], _tool_result(False, error="child failed"))
    )
    payload = await _dispatch(_fake_request(cs), "runtime_exec", {})
    assert payload["success"] is False  # fail-open：200 + success=false
    assert payload["error"] == "child failed"


# ---------------------------------------------------------------------------
# _dispatch_structured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_structured_output_json_string_parsed(monkeypatch):
    cs = SimpleNamespace(
        tools=_FakeTools(
            ["runtime_probe"],
            _tool_result(True, output=json.dumps({"runtimes": [1, 2]})),
        )
    )
    payload = await _dispatch_structured(_fake_request(cs), "runtime_probe", {})
    assert payload["output"] == {"runtimes": [1, 2]}  # 字符串已反序列化


@pytest.mark.asyncio()
async def test_structured_output_invalid_json_kept_as_string(monkeypatch):
    cs = SimpleNamespace(
        tools=_FakeTools(["runtime_probe"], _tool_result(True, output="{bad json"))
    )
    payload = await _dispatch_structured(_fake_request(cs), "runtime_probe", {})
    assert payload["output"] == "{bad json"  # 解析失败保留原串，前端可降级


@pytest.mark.asyncio()
async def test_structured_output_non_string_unchanged(monkeypatch):
    cs = SimpleNamespace(
        tools=_FakeTools(["runtime_probe"], _tool_result(True, output={"already": "dict"}))
    )
    payload = await _dispatch_structured(_fake_request(cs), "runtime_probe", {})
    assert payload["output"] == {"already": "dict"}


@pytest.mark.asyncio()
async def test_structured_failure_path_also_parsed(monkeypatch):
    # runtime_exec 失败时也把 ExecutionResult 序列化进 output——
    # 失败路径同样反序列化，前端才能读到 error/timed_out 字段
    exec_result_json = json.dumps({"exit_code": 1, "error": "boom", "timed_out": True})
    cs = SimpleNamespace(
        tools=_FakeTools(
            ["runtime_exec"],
            _tool_result(False, output=exec_result_json, error="exec failed"),
        )
    )
    payload = await _dispatch_structured(_fake_request(cs), "runtime_exec", {})
    assert payload["success"] is False
    assert payload["output"]["timed_out"] is True
    assert payload["error"] == "exec failed"
