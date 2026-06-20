"""ghm 计算端到端集成测试 — 真打 ghm CLI,验证完整链路。

链路:POST /api/v1/chat → mock LLM 返回 tool_call(compute_shock) →
ComputeToolAdapter → SubprocessComputeAdapter → 真实 ghm CLI →
TOOL message 落库 + tool_invoked 事件 emit。

跳过条件:``GHM_PYTHON`` 环境变量指向的 conda python 不存在(或默认
``/home/fz/anaconda3/envs/ghm/bin/python`` 不存在)。CI 上可显式设置
``GHM_TEST_DISABLED=1`` 强制跳过。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.adapters.out.compute.subprocess_adapter import SubprocessComputeAdapter
from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.compute_tool_adapter import ComputeToolAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.api.hex_routes import get_chat_service
from backend.application.services.chat_service import ChatService
from sage_core import Message, Role, ToolCall
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_PATH = "/api/v1/chat"

# 仅在 hex 模式 + ghm 可用时跑
# PG-A1: local default 同步 main.py flip (hex→legacy)
_API_MODE = os.environ.get("API_MODE", "legacy").lower()

_GHM_PYTHON = os.environ.get(
    "GHM_PYTHON",
    "/home/fz/anaconda3/envs/ghm/bin/python",
)
_GHM_PROJECT_DIR = os.environ.get(
    "GHM_PROJECT_DIR",
    "/home/fz/project/ghm",
)
_GHM_AVAILABLE = (
    not os.environ.get("GHM_TEST_DISABLED")
    and _API_MODE == "hex"
    and Path(_GHM_PYTHON).is_file()
    and os.access(_GHM_PYTHON, os.X_OK)
    and Path(_GHM_PROJECT_DIR).is_dir()
)

requires_ghm = pytest.mark.skipif(
    not _GHM_AVAILABLE,
    reason=(
        f"ghm 环境不可用 (GHM_PYTHON={_GHM_PYTHON}, GHM_PROJECT_DIR={_GHM_PROJECT_DIR},"
        f" API_MODE={_API_MODE!r}, GHM_TEST_DISABLED={os.environ.get('GHM_TEST_DISABLED')!r})"
    ),
)


def _make_ghm_config() -> dict[str, Any]:
    """E2E 用的 ghm 配置:走 python_module 回退,操作只含 compute_shock。"""
    return {
        "enabled": True,
        "timeout_seconds": 30,
        "adapter": "subprocess",
        "subprocess": {
            "python_module": {
                "python": _GHM_PYTHON,
                "module": "ghm",
                "working_dir": _GHM_PROJECT_DIR,
            },
            "path_lookup_name": "ghm-cli",
        },
        "operations": [
            {
                "name": "compute_shock",
                "cli_subcommand": ["core", "shock"],
                "description": "正激波计算",
                "params_schema": {
                    "type": "object",
                    "required": ["mach", "gamma", "p1", "t1"],
                    "properties": {
                        "mach": {"type": "number"},
                        "gamma": {"type": "number"},
                        "p1": {"type": "number"},
                        "t1": {"type": "number"},
                    },
                },
            }
        ],
    }


@pytest_asyncio.fixture
async def ghm_e2e_client():
    """装配:真实 SubprocessComputeAdapter + ComputeToolAdapter,mock LLM 返回 tool_call。"""
    compute = SubprocessComputeAdapter(_make_ghm_config())
    tools = ComputeToolAdapter(compute=compute, inner=InprocToolAdapter())

    # 第一次调用 LLM 时返回 tool_call(compute_shock)
    llm_response_with_tool_call = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                name="compute_shock",
                args={"mach": 6.5, "gamma": 1.4, "p1": 1000.0, "t1": 250.0},
                id="tool_call_1",
            )
        ],
    )
    mock_llm = MockLLMAdapter(responses=[llm_response_with_tool_call])

    fake_svc = ChatService(
        llm=mock_llm,
        tools=tools,
        skills=None,
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )

    saved_override = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, fake_svc
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_chat_service] = saved_override
        else:
            app.dependency_overrides.pop(get_chat_service, None)


@pytest.mark.asyncio()
@requires_ghm
async def test_e2e_chat_triggers_real_ghm_compute(ghm_e2e_client) -> None:
    """完整链路:LLM 选 compute_shock → 真打 ghm → TOOL message 含真实结果。"""
    client, svc = ghm_e2e_client

    sid = await svc.storage.create_session()

    resp = await client.post(
        CHAT_PATH,
        json={"session_id": sid, "message": "算 mach 6.5 的激波后参数"},
    )
    assert resp.status_code == 200, resp.text

    # 验证 storage 中落了 TOOL 消息
    stored = await svc.storage.get_messages(sid, limit=50)
    tool_messages = [m for m in stored if m.role == Role.TOOL]
    assert len(tool_messages) == 1, f"expected 1 TOOL message, got {len(tool_messages)}"

    tool_msg = tool_messages[0]
    # 真实计算结果应含关键字段:M1, M2, p2 等(ghm core shock 输出键)
    # tool_msg.content 应是 JSON 字符串
    assert tool_msg.tool_call_id == "tool_call_1"
    assert "M2" in tool_msg.content, f"expected M2 in result, got: {tool_msg.content!r}"
    assert "p2" in tool_msg.content, f"expected p2 in result, got: {tool_msg.content!r}"
    # 输入 mach=6.5 应回填 M1=6.5
    assert "6.5" in tool_msg.content


@pytest.mark.asyncio()
@requires_ghm
async def test_e2e_unknown_compute_op_returns_error_in_tool_message(
    ghm_e2e_client,
) -> None:
    """LLM 调一个未声明的 operation → TOOL message 标记失败,不破坏链路。"""
    client, svc = ghm_e2e_client

    # 重置 mock LLM,让它返回一个错的 tool_call
    svc.llm._responses = [  # type: ignore[attr-defined]
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(name="not_a_real_op", args={}, id="bad_call"),
            ],
        )
    ]
    svc.llm._index = 0  # type: ignore[attr-defined]

    sid = await svc.storage.create_session()

    resp = await client.post(
        CHAT_PATH,
        json={"session_id": sid, "message": "随便算点啥"},
    )
    assert resp.status_code == 200, resp.text

    stored = await svc.storage.get_messages(sid, limit=50)
    tool_messages = [m for m in stored if m.role == Role.TOOL]
    assert len(tool_messages) == 1
    # 失败时 tool_message.content 取 error 信息
    assert "not_a_real_op" in tool_messages[0].content
