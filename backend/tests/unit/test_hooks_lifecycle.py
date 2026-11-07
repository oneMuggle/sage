"""Phase 2 生命周期事件单元测试。

覆盖:
- HOOK_EVENTS 白名单新增 session_start / session_stop / error_occurred
- build_session_payload / build_error_payload 结构
- run_event_hooks_sync 同步桥接 (无循环 → 执行; 有循环 → fail-open no-op)
- agent._maybe_fire_error_hook 仅在 is_error 且确有钩子时触发
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from backend.hooks.config import HOOK_EVENTS, HookConfig, validate_hooks
from backend.hooks.runner import (
    DECISION_ALLOW,
    DECISION_NOOP,
    build_error_payload,
    build_session_payload,
    run_event_hooks,
    run_event_hooks_sync,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform == "win32", reason="hooks shell 引用在 Windows cmd.exe 下不兼容（产品缺口）"),
]

PY = sys.executable


def _cfg(command: str, event: str, matcher: str = "*", timeout: float = 5.0) -> HookConfig:
    return HookConfig(event=event, command=command, matcher=matcher, timeout_seconds=timeout)


# ==================== 事件白名单 ====================


def test_lifecycle_events_in_whitelist():
    assert "session_start" in HOOK_EVENTS
    assert "session_stop" in HOOK_EVENTS
    assert "error_occurred" in HOOK_EVENTS


def test_original_events_preserved():
    """Phase 2 不破坏既有 4 事件。"""
    for event in ("pre_tool_use", "post_tool_use", "user_prompt_submit", "stop"):
        assert event in HOOK_EVENTS


def test_validate_accepts_lifecycle_events():
    hooks = validate_hooks(
        [
            {"event": "session_start", "command": "echo a"},
            {"event": "session_stop", "command": "echo b"},
            {"event": "error_occurred", "command": "echo c"},
        ]
    )
    assert [h.event for h in hooks] == ["session_start", "session_stop", "error_occurred"]


# ==================== payload 构建 ====================


def test_build_session_payload_minimal():
    payload = build_session_payload("session_start", "sess-123")
    assert payload["hook_event_name"] == "session_start"
    assert payload["session_id"] == "sess-123"
    assert "timestamp" in payload
    assert "workspace" not in payload
    assert "git_branch" not in payload


def test_build_session_payload_with_metadata():
    payload = build_session_payload(
        "session_start", "s", workspace="/repo", git_branch="main"
    )
    assert payload["workspace"] == "/repo"
    assert payload["git_branch"] == "main"


def test_build_session_payload_extra_merges():
    payload = build_session_payload("session_start", "s", extra={"title": "新会话"})
    assert payload["title"] == "新会话"


def test_build_error_payload_shape():
    payload = build_error_payload(
        error_type="tool_error",
        error_message="Command exited with code 1",
        tool_name="bash",
    )
    assert payload["hook_event_name"] == "error_occurred"
    assert payload["error_type"] == "tool_error"
    assert payload["error_message"] == "Command exited with code 1"
    assert payload["tool_name"] == "bash"
    assert "timestamp" in payload


def test_build_error_payload_truncates_traceback():
    payload = build_error_payload(
        error_type="tool_error",
        error_message="boom",
        error_traceback="x" * 10000,
    )
    assert len(payload["error_traceback"]) == 4096


def test_build_error_payload_attempt_count_only_when_retried():
    assert "attempt_count" not in build_error_payload("tool_error", "e", attempt_count=1)
    assert build_error_payload("tool_error", "e", attempt_count=3)["attempt_count"] == 3


# ==================== run_event_hooks_sync ====================


def test_sync_bridge_runs_hook_without_running_loop():
    """无运行中的事件循环 → 同步桥接正常执行钩子。"""
    deny_cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny", "reason": "blocked"}}))'"""
    )
    hooks = [_cfg(deny_cmd, "session_start")]
    payload = build_session_payload("session_start", "s1")
    outcome = run_event_hooks_sync(hooks, "session_start", "", payload)
    assert outcome.denied
    assert outcome.reason == "blocked"


def test_sync_bridge_allow_when_no_hooks():
    outcome = run_event_hooks_sync([], "session_stop", "", {"hook_event_name": "session_stop"})
    assert outcome.decision == DECISION_ALLOW


def test_sync_bridge_is_noop_inside_running_loop():
    """已有运行中的循环 → 不阻塞, 降级 no-op (fail-open)。"""

    async def _inner():
        deny_cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny"}}))'"""
        hooks = [_cfg(deny_cmd, "session_start")]
        return run_event_hooks_sync(
            hooks, "session_start", "", build_session_payload("session_start", "s")
        )

    outcome = asyncio.run(_inner())
    assert outcome.decision == DECISION_NOOP
    assert outcome.reason == "event loop running"


# ==================== 事件过滤 ====================


@pytest.mark.asyncio()
async def test_lifecycle_hook_does_not_fire_for_tool_events():
    """session_start 钩子不应对 pre_tool_use 生效 (事件名精确匹配)。"""
    deny_cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny"}}))'"""
    hooks = [_cfg(deny_cmd, "session_start")]
    outcome = await run_event_hooks(
        hooks, "pre_tool_use", "bash", {"hook_event_name": "pre_tool_use"}
    )
    assert outcome.decision == DECISION_ALLOW


@pytest.mark.asyncio()
async def test_error_hook_matches_tool_name():
    """error_occurred 钩子的 matcher 可针对特定工具。"""
    deny_cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny"}}))'"""
    hooks = [_cfg(deny_cmd, "error_occurred", matcher="bash")]
    matched = await run_event_hooks(hooks, "error_occurred", "bash", {})
    assert matched.denied
    unmatched = await run_event_hooks(hooks, "error_occurred", "read_file", {})
    assert unmatched.decision == DECISION_ALLOW


# ==================== agent._maybe_fire_error_hook ====================


@pytest.mark.asyncio()
async def test_agent_error_hook_skipped_when_not_error():
    """is_error=False → 不触发任何钩子。"""
    from backend.core.legacy.agent import SageAgent

    agent = SageAgent(bare=True)
    deny_cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny"}}))'"""
    hooks = [_cfg(deny_cmd, "error_occurred")]
    # 不抛异常即通过 —— 内部不触发钩子
    await agent._maybe_fire_error_hook(hooks, "bash", "ok output", False)


@pytest.mark.asyncio()
async def test_agent_error_hook_skipped_when_no_hooks():
    from backend.core.legacy.agent import SageAgent

    agent = SageAgent(bare=True)
    await agent._maybe_fire_error_hook([], "bash", "error!", True)


@pytest.mark.asyncio()
async def test_agent_error_hook_fires_on_error(tmp_path):
    """is_error=True 且钩子存在 → 钩子收到 error_occurred payload。"""
    from backend.core.legacy.agent import SageAgent

    script = tmp_path / "err_hook.py"
    script.write_text(
        "import json, sys\n"
        "p = json.load(sys.stdin)\n"
        "assert p['hook_event_name'] == 'error_occurred', p\n"
        "assert p['error_type'] == 'tool_error', p\n"
        "with open(sys.argv[1], 'w') as f:\n"
        "    f.write(p['error_message'])\n"
        "print(json.dumps({'decision': 'allow'}))\n",
        encoding="utf-8",
    )
    marker = tmp_path / "seen.txt"
    cmd = f"{PY} {script} {marker}"

    agent = SageAgent(bare=True)
    hooks = [_cfg(cmd, "error_occurred")]
    await agent._maybe_fire_error_hook(hooks, "bash", "Command exited with code 1", True)

    assert marker.exists(), "hook script should have run on error"
    assert "Command exited with code 1" in marker.read_text(encoding="utf-8")


@pytest.mark.asyncio()
async def test_agent_error_hook_fail_open_on_bad_hook():
    """钩子命令故障 → 不冒泡异常 (fail-open)。"""
    from backend.core.legacy.agent import SageAgent

    agent = SageAgent(bare=True)
    hooks = [_cfg("exit 7", "error_occurred")]
    await agent._maybe_fire_error_hook(hooks, "bash", "boom", True)
