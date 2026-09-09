"""C2 (2026-09-09) — 审批决策落库单测。

- repo append/list 往返
- gate gui 应答落库（approved=true, answered_by=gui）
- gate 超时 default-deny 落库（answered_by=timeout）
- AutoApproveEnforcer 自动放行落库（answered_by=auto）
"""

from __future__ import annotations

import asyncio

import pytest

from backend.data import database as db_mod
from backend.data.approval_decision_repo import ApprovalDecisionRepository


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return ApprovalDecisionRepository()


def test_append_and_list_roundtrip(repo):
    import time

    created_ms = int(time.time() * 1000) - 100
    repo.append(
        tool_name="bash",
        approved=True,
        answered_by="gui",
        request_id="req-1",
        session_id="s-1",
        run_id="orch-a",
        task_id="t1",
        args_summary='{"command": "ls"}',
        risk="safe",
        created_at=created_ms,
    )
    rows = repo.list()
    assert len(rows) == 1
    row = rows[0]
    assert row.tool_name == "bash"
    assert row.approved is True
    assert row.answered_by == "gui"
    assert row.session_id == "s-1"
    assert row.run_id == "orch-a"
    assert row.task_id == "t1"
    assert row.latency_ms is not None
    assert row.latency_ms >= 100


@pytest.mark.asyncio()
async def test_gate_gui_answer_recorded(repo):
    from backend.services.permission_gate import ApprovalGate, ApprovalRequest

    gate = ApprovalGate()
    req = ApprovalRequest.create("bash", {"command": "ls"}, "safe", "原因")
    pending = asyncio.create_task(gate.request(req, timeout=5))
    await asyncio.sleep(0.02)
    assert gate.answer(req.request_id, approved=True) is True
    answer = await pending
    assert answer.answered_by == "gui"

    rows = repo.list()
    assert len(rows) == 1
    assert rows[0].request_id == req.request_id
    assert rows[0].approved is True
    assert rows[0].answered_by == "gui"


@pytest.mark.asyncio()
async def test_gate_timeout_recorded_as_deny(repo):
    from backend.services.permission_gate import ApprovalGate, ApprovalRequest

    gate = ApprovalGate()
    req = ApprovalRequest.create("bash", {"command": "rm -rf x"}, "destructive", "原因")
    answer = await gate.request(req, timeout=0.05)
    assert answer.answered_by == "timeout"
    assert answer.approved is False

    rows = repo.list()
    assert len(rows) == 1
    assert rows[0].approved is False
    assert rows[0].answered_by == "timeout"
    assert rows[0].risk == "destructive"


@pytest.mark.asyncio()
async def test_auto_approve_recorded(repo):
    from backend.orchestration.subagent_approval import AutoApproveEnforcer
    from backend.tools.permissions import PermissionDecision

    class _StubBase:
        def check(self, tool_name, args=None):
            return PermissionDecision(
                allowed=False, needs_approval=True, reason="需要审批"
            )

    enforcer = AutoApproveEnforcer(_StubBase())
    decision = enforcer.check("web_fetch", {"url": "https://x"})
    assert decision.needs_approval is False
    assert decision.allowed is True

    rows = repo.list()
    assert len(rows) == 1
    assert rows[0].tool_name == "web_fetch"
    assert rows[0].approved is True
    assert rows[0].answered_by == "auto"


@pytest.mark.asyncio()
async def test_recording_failure_does_not_block_approval(repo, monkeypatch):
    """落库失败必须静默 —— 审批流照常返回（降级铁律）。"""
    from backend.services.permission_gate import ApprovalGate, ApprovalRequest

    class _BrokenRepo:
        def append(self, **kwargs):
            raise RuntimeError("db down")

    def _broken():
        return _BrokenRepo()

    monkeypatch.setattr(
        "backend.data.approval_decision_repo.ApprovalDecisionRepository", _broken
    )
    gate = ApprovalGate()
    req = ApprovalRequest.create("bash", {"command": "ls"}, "safe", "原因")
    pending = asyncio.create_task(gate.request(req, timeout=5))
    await asyncio.sleep(0.02)
    assert gate.answer(req.request_id, approved=True) is True
    answer = await pending
    assert answer.answered_by == "gui"
