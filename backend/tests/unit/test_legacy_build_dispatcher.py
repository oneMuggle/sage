"""legacy_routes._build_orchestration_dispatcher 直接单测。

集成测试（构造完整 ChatRequest + SSE 长连接捕获 NDJSON）成本高，
按 plan 约定退化为直接单测包装逻辑，覆盖：
1. 合法 run_id → 正常返回 ChatDispatcher 实例；
2. 非法 run_id → ValueError 重抛为前端可读中文文案（拒绝语义保留，
   不吞错、不降级 single）。
"""

from __future__ import annotations

import asyncio
import re

import pytest

from backend.api.legacy_routes import _build_orchestration_dispatcher
from backend.orchestration.chat_dispatcher import ChatDispatcher

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


@pytest.mark.asyncio()
async def test_build_dispatcher_valid_run_id_returns_dispatcher() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    dispatcher = _build_orchestration_dispatcher(
        stream_id="stream-1",
        entry_queue=queue,
        run_id="orch-abc123",
        llm_config=None,
        total_tasks=3,
        workspace_root=None,
    )
    assert isinstance(dispatcher, ChatDispatcher)
    assert dispatcher.run_id == "orch-abc123"
    assert dispatcher.total_tasks == 3


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "bad_run_id",
    [
        "../etc/passwd",
        "run id",
        "",
        "x" * 129,
        "中文run",
    ],
)
async def test_build_dispatcher_invalid_run_id_raises_friendly_valueerror(
    bad_run_id: str,
) -> None:
    """非法 run_id 仍抛 ValueError（拒绝语义），文案改为前端可读中文。"""
    queue: asyncio.Queue = asyncio.Queue()
    with pytest.raises(ValueError, match="编排启动失败") as exc_info:
        _build_orchestration_dispatcher(
            stream_id="stream-1",
            entry_queue=queue,
            run_id=bad_run_id,
            llm_config=None,
            total_tasks=1,
            workspace_root=None,
        )
    message = str(exc_info.value)
    assert "编排启动失败" in message
    assert "请刷新后重试" in message
    # 保留原始诊断（含 repr），便于定位根因；且该 run_id 本身不合法。
    assert "非法 run_id" in message
    assert not _RUN_ID_RE.fullmatch(bad_run_id)
