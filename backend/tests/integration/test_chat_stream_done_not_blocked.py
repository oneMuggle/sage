"""回归（2026-11-02）：DONE 不得被收尾副作用阻塞。

实测现场：assistant 行已于 21:22:18 落盘，前端直到 21:24:34 才收到
``done``，光标在正文末尾停留 136 秒。根因是 producer 在 DONE 入队前
inline await stop hooks 与记忆抽取；现两者移入后台任务
（``_spawn_post_turn_task``），DONE 立即送达。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.api.legacy_routes import drain_post_turn_tasks
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.session_repo import SessionRepository
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"


@pytest.mark.asyncio()
async def test_done_arrives_while_post_turn_side_effects_still_running(client):
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_extract(*args, **kwargs):  # noqa: ARG001 — 测试夹具
        started.set()
        await release.wait()

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="即时完成")

    session = SessionRepository().create(title="DONE 解耦回归")

    # 全局 app 可能被更早跑过 lifespan 的测试留下 app.state.lifecycle
    # （backend/main.py 的 lifespan 安装后不会清理）。此时收尾任务走
    # lifecycle.on_turn_complete，本测试 mock 的 _extract_legacy_chat_memory
    # 永远不会被调用 → started 永不置位。显式置 None 保证走 legacy 分支。
    prev_lifecycle = getattr(app.state, "lifecycle", None)
    app.state.lifecycle = None

    try:
        # py3.8 不支持括号式多上下文写法，这里用嵌套 with。
        # 同时隔离 stop hooks：settings 库在 xdist worker 间共享，其它测试
        # 写入的钩子会让收尾任务先跑钩子（默认超时 10s），拖延到本次超时。
        with patch("backend.api.legacy_routes.SageAgent") as MockAgent, patch(
            "backend.api.legacy_routes._extract_legacy_chat_memory",
            _slow_extract,
        ), patch("backend.hooks.config.load_hooks", return_value=[]):
            MockAgent.return_value.run_loop = mock_run_loop
            MockAgent.return_value.memory_manager = None

            create_resp = await client.post(
                CHAT_STREAM_PATH,
                json={"session_id": session.id, "message": "帮我记住这个偏好"},
            )
            assert create_resp.status_code == 200, create_resp.text
            stream_id = create_resp.json()["streamId"]

            # py38 CI 调度延迟较高，放宽 DONE 到达超时（原 2.0s → 5.0s）
            attach_resp = await asyncio.wait_for(
                client.get(f"{CHAT_STREAM_PATH}/{stream_id}"), timeout=5.0
            )
            assert attach_resp.status_code == 200
            assert "done" in attach_resp.text
            # 收尾任务已启动但尚未完成 —— DONE 已先行送达。
            # py38 CI 调度延迟较高，放宽后台任务启动超时（原 1.0s → 3.0s）
            await asyncio.wait_for(started.wait(), timeout=3.0)
            assert not release.is_set()
    finally:
        release.set()
        # py38 CI 调度延迟较高，放宽 drain 超时（原 1.0s → 3.0s）
        await drain_post_turn_tasks(timeout=3.0)
        app.state.lifecycle = prev_lifecycle
