"""M3 控制面注册表单元测试（进程内状态机，无 CDP）。"""

from __future__ import annotations

import threading

import pytest

from backend.services.browser_control import (
    ACTION_TO_STATE,
    PAUSED_ERROR_PREFIX,
    TAKEOVER_ERROR_PREFIX,
    VALID_CONTROL_ACTIONS,
    BrowserControlRegistry,
    BrowserControlState,
    get_browser_control,
    reset_browser_control_for_tests,
)

pytestmark = pytest.mark.unit


def test_state_enum_values_match_frontend_contract():
    assert BrowserControlState.AGENT.value == "agent"
    assert BrowserControlState.PAUSED.value == "paused"
    assert BrowserControlState.USER_TAKEOVER.value == "user_takeover"


def test_error_prefixes_are_exact():
    """前缀是前端/提示逻辑契约，不允许改名。"""
    assert PAUSED_ERROR_PREFIX == "user_paused: "
    assert TAKEOVER_ERROR_PREFIX == "user_takeover: "


def test_unknown_session_defaults_to_agent():
    registry = BrowserControlRegistry()
    assert registry.get_state("ghost") is BrowserControlState.AGENT
    assert registry.snapshot() == {}


def test_set_get_reset_roundtrip():
    registry = BrowserControlRegistry()
    registry.set_state("s1", BrowserControlState.PAUSED)
    assert registry.get_state("s1") is BrowserControlState.PAUSED
    assert registry.snapshot() == {"s1": "paused"}

    registry.set_state("s1", BrowserControlState.USER_TAKEOVER)
    assert registry.snapshot() == {"s1": "user_takeover"}

    # 回到默认 agent → 条目移除（snapshot 只保留非默认状态）
    registry.set_state("s1", BrowserControlState.AGENT)
    assert registry.snapshot() == {}
    assert registry.get_state("s1") is BrowserControlState.AGENT

    registry.set_state("s2", BrowserControlState.PAUSED)
    registry.reset("s2")
    assert registry.get_state("s2") is BrowserControlState.AGENT
    # reset 未知会话是幂等 no-op
    registry.reset("never-seen")
    assert registry.snapshot() == {}


def test_set_state_coerces_strings_and_rejects_bad_input():
    registry = BrowserControlRegistry()
    registry.set_state("s1", "paused")
    assert registry.get_state("s1") is BrowserControlState.PAUSED
    with pytest.raises(ValueError, match="not a valid BrowserControlState"):
        registry.set_state("s1", "bogus")
    with pytest.raises(ValueError, match="session_id"):
        registry.set_state("", BrowserControlState.PAUSED)


def test_action_mapping_matches_contract():
    assert VALID_CONTROL_ACTIONS == ("pause", "resume", "takeover", "return")
    expected = {
        "pause": BrowserControlState.PAUSED,
        "resume": BrowserControlState.AGENT,
        "takeover": BrowserControlState.USER_TAKEOVER,
        "return": BrowserControlState.AGENT,
    }
    assert expected == ACTION_TO_STATE


def test_process_singleton_and_test_reset():
    first = get_browser_control()
    assert get_browser_control() is first
    first.set_state("s1", BrowserControlState.USER_TAKEOVER)
    reset_browser_control_for_tests()
    # 重置不清除单例本身，只清空状态
    assert get_browser_control() is first
    assert first.snapshot() == {}


def test_concurrent_reads_and_writes_are_safe():
    registry = BrowserControlRegistry()
    errors: list = []

    def worker(index: int) -> None:
        try:
            for step in range(200):
                session_id = f"s{index % 4}"
                state = (
                    BrowserControlState.PAUSED
                    if step % 2
                    else BrowserControlState.USER_TAKEOVER
                )
                registry.set_state(session_id, state)
                registry.get_state(session_id)
                registry.snapshot()
                registry.reset(f"tmp{index}")
        except Exception as exc:  # noqa: BLE001 — 线程内异常收集后断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert set(registry.snapshot()) <= {"s0", "s1", "s2", "s3"}
