"""M1 工具安全加固 — ApprovalGate 单测。

覆盖: 应答解析 Future、未知 id、超时 default-deny、pending 快照、
单例访问器、参数摘要脱敏。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.permission_gate import (
    ARG_VALUE_MAX_CHARS,
    ApprovalAnswer,
    ApprovalGate,
    ApprovalRequest,
    get_permission_gate,
    init_permission_gate,
    reset_permission_gate,
    summarize_tool_args,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_global_gate():
    """每个测试前后重置全局 gate, 避免跨测试泄漏。"""
    reset_permission_gate()
    yield
    reset_permission_gate()


def _make_request(tool_name="terminal"):
    return ApprovalRequest.create(
        tool_name=tool_name,
        args={"command": "ls"},
        risk="safe",
        message="需要确认",
    )


# ---------------------------------------------------------------------------
# Future 解析
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_gate_answer_resolves_pending_request_future():
    """并发任务调用 answer() → request() 的 await 被解析为 gui 应答。"""
    # Arrange
    gate = ApprovalGate()
    req = _make_request()

    async def answer_later():
        await asyncio.sleep(0.01)
        assert gate.answer(req.request_id, approved=True, remember=True) is True

    # Act
    answer_task = asyncio.create_task(answer_later())
    answer = await gate.request(req, timeout=5.0)
    await answer_task

    # Assert
    assert answer.approved is True
    assert answer.remember is True
    assert answer.answered_by == "gui"


@pytest.mark.asyncio()
async def test_gate_answer_false_propagates_denial():
    """answer(approved=False) → request() 收到拒绝应答。"""
    # Arrange
    gate = ApprovalGate()
    req = _make_request()

    async def deny_later():
        await asyncio.sleep(0.01)
        gate.answer(req.request_id, approved=False)

    # Act
    task = asyncio.create_task(deny_later())
    answer = await gate.request(req, timeout=5.0)
    await task

    # Assert
    assert answer.approved is False
    assert answer.answered_by == "gui"


def test_gate_answer_unknown_id_returns_false():
    """未知 request_id → False (路由层转成 unknown_or_expired)。"""
    # Arrange
    gate = ApprovalGate()

    # Act / Assert
    assert gate.answer("no-such-id", approved=True) is False


@pytest.mark.asyncio()
async def test_gate_answer_after_expiry_returns_false():
    """超时清理后, 迟到的 answer() → False。"""
    # Arrange
    gate = ApprovalGate()
    req = _make_request()

    # Act —— 用极短超时让请求过期
    answer = await gate.request(req, timeout=0.05)
    late = gate.answer(req.request_id, approved=True)

    # Assert
    assert answer.approved is False
    assert answer.answered_by == "timeout"
    assert late is False


@pytest.mark.asyncio()
async def test_gate_timeout_returns_default_deny_without_answer():
    """无应答超时 → ApprovalAnswer(False, False, "timeout")（fail-closed）。"""
    # Arrange
    gate = ApprovalGate()
    req = _make_request()

    # Act
    answer = await gate.request(req, timeout=0.05)

    # Assert
    assert isinstance(answer, ApprovalAnswer)
    assert answer.approved is False
    assert answer.remember is False
    assert answer.answered_by == "timeout"


@pytest.mark.asyncio()
async def test_gate_double_answer_second_call_returns_false():
    """同一请求被应答两次 → 第二次 False。"""
    # Arrange
    gate = ApprovalGate()
    req = _make_request()

    async def answer_twice():
        await asyncio.sleep(0.01)
        assert gate.answer(req.request_id, approved=True) is True
        # Future 已解析但 request() 的 finally 可能尚未清理;
        # done 的 Future 不允许再次 set_result → 返回 False
        assert gate.answer(req.request_id, approved=False) is False

    # Act
    task = asyncio.create_task(answer_twice())
    await gate.request(req, timeout=5.0)
    await task


# ---------------------------------------------------------------------------
# pending / get_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_gate_pending_lists_only_unanswered_requests():
    """pending() 只返回未应答请求; 应答后即消失。"""
    # Arrange
    gate = ApprovalGate()
    r1 = _make_request("write_file")
    r2 = _make_request("terminal")

    async def answer_one():
        # 等 r1 挂起后应答它
        for _ in range(200):
            if gate.get_request(r1.request_id) is not None:
                break
            await asyncio.sleep(0.005)
        gate.answer(r1.request_id, approved=True)

    task = asyncio.create_task(answer_one())

    # Act: r1 在 await, 同时检查 r2 的 pending 视图
    r2_holder = asyncio.create_task(gate.request(r2, timeout=0.05))
    await gate.request(r1, timeout=5.0)

    # Assert: r1 已应答, pending 只剩 r2 (直到它自己超时)
    pending_ids = [r.request_id for r in gate.pending()]
    assert r1.request_id not in pending_ids
    assert r2.request_id in pending_ids
    await r2_holder
    await task
    assert gate.pending() == []


def test_gate_get_request_returns_none_for_unknown():
    """get_request 未知 id → None。"""
    # Arrange
    gate = ApprovalGate()

    # Act / Assert
    assert gate.get_request("nope") is None


# ---------------------------------------------------------------------------
# 单例访问器
# ---------------------------------------------------------------------------


def test_global_gate_none_until_initialized():
    """未 init 时 get_permission_gate() → None (调用方 default-deny)。"""
    # Arrange / Act / Assert
    assert get_permission_gate() is None


def test_init_permission_gate_returns_singleton():
    """init 后 get 返回同一实例。"""
    # Arrange / Act
    gate = init_permission_gate()

    # Assert
    assert get_permission_gate() is gate
    assert init_permission_gate() is not gate  # 再次 init 会替换实例


# ---------------------------------------------------------------------------
# 参数摘要脱敏
# ---------------------------------------------------------------------------


def test_summarize_tool_args_redacts_secret_keys():
    """键名含 key/token/password/secret/credential/auth 的值 → ***。"""
    # Arrange
    args = {
        "api_key": "sk-super-secret",
        "auth_token": "ghp_xxx",
        "db_password": "hunter2",
        "command": "ls",
    }

    # Act
    summary = summarize_tool_args(args)

    # Assert
    assert "sk-super-secret" not in summary
    assert "ghp_xxx" not in summary
    assert "hunter2" not in summary
    assert "***" in summary
    assert "ls" in summary


def test_summarize_tool_args_truncates_long_values():
    """长值截断到 200 字符 + 截断标记。"""
    # Arrange
    args = {"content": "x" * 5000}

    # Act
    summary = summarize_tool_args(args)

    # Assert
    assert "x" * (ARG_VALUE_MAX_CHARS + 1) not in summary
    assert "已截断" in summary


def test_summarize_tool_args_handles_empty_and_non_string():
    """空参数 / 非字符串值不报错。"""
    # Arrange / Act / Assert
    assert summarize_tool_args(None) == "{}"
    assert summarize_tool_args({}) == "{}"
    summary = summarize_tool_args({"nested": {"a": 1}, "flag": True})
    assert "a" in summary


def test_approval_request_to_dict_shape_matches_frontend_contract():
    """to_dict 的键集合是前端契约——改动需同步前端 agent。"""
    # Arrange
    req = _make_request()

    # Act
    payload = req.to_dict()

    # Assert
    assert set(payload.keys()) == {
        "request_id",
        "tool_name",
        "args_summary",
        "risk",
        "message",
        "created_at",
    }


def test_summarize_tool_args_redacts_nested_secret_keys():
    """FIX-5: 脱敏递归进入嵌套 dict/list —— 顶层脱敏挡不住嵌套泄漏。"""
    # Arrange
    args = {
        "config": {"api_key": "sk-12345", "inner": {"auth_token": "tok-9"}},
        "servers": [{"password": "hunter2"}],
        "plain": "visible",
    }

    # Act
    summary = summarize_tool_args(args)

    # Assert
    assert "sk-12345" not in summary
    assert "tok-9" not in summary
    assert "hunter2" not in summary
    assert "***" in summary
    assert "visible" in summary  # 非秘密值不受影响


def test_summarize_tool_args_survives_cyclic_structures():
    """深度封顶切断自引用结构 —— 不爆栈, 返回合法字符串。"""
    # Arrange
    cycle: dict = {"name": "x"}
    cycle["self"] = cycle

    # Act
    summary = summarize_tool_args({"payload": cycle})

    # Assert
    assert isinstance(summary, str)
    assert "x" in summary
