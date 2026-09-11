"""Telegram 审批转发与命令测试（Round 10）"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest

from backend.gateway.telegram import TelegramConfig, TelegramGateway

pytestmark = pytest.mark.unit


class FakeTransport:
    def __init__(self):
        self.sent: list = []

    def get_updates(self, offset, timeout_seconds):
        return []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeGate:
    def __init__(self):
        self.requests: list = []
        self.answers: list = []

    def pending(self):
        return list(self.requests)

    def get_request(self, request_id):
        for r in self.requests:
            if r.request_id == request_id:
                return r
        return None

    def answer(self, request_id, approved, remember=False):
        for i, r in enumerate(self.requests):
            if r.request_id == request_id:
                self.answers.append((request_id, approved))
                self.requests.pop(i)
                return True
        return False


def _req(rid: str, tool: str = "bash", risk: str = "destructive"):
    return SimpleNamespace(
        request_id=rid,
        tool_name=tool,
        args_summary="{}",
        risk=risk,
        message="危险命令需要审批",
        created_at=0,
    )


@pytest.fixture()
def tmp_db(monkeypatch):
    from backend.data.database import Database

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
    import backend.data.database as db_mod

    monkeypatch.setattr(db_mod, "_db", db)
    yield db
    db.close()


def _make(tmp_db, gate):
    config = TelegramConfig(
        bot_token="tok", allowed_chat_ids=["111"], poll_timeout_seconds=0
    )
    return TelegramGateway(
        config=config,
        transport=FakeTransport(),
        llm_factory=lambda sid: None,
        db=tmp_db,
    )


class TestApprovalForwarding:
    def test_new_pending_forwarded_once(self, tmp_db):
        import backend.services.permission_gate as pg

        gate = FakeGate()
        gate.requests.append(_req("aaaabbbb-1111-2222-3333-444444444444"))
        monkey = pytest.MonkeyPatch()
        monkey.setattr(pg, "_global_gate", gate)
        gateway = _make(tmp_db, gate)
        gateway.transport.updates = []  # 无消息也触发转发
        gateway.poll_once()
        gateway.poll_once()
        sent = [t for _, t in gateway.transport.sent]
        assert sum("待审批" in t for t in sent) == 1  # 去重
        assert "/approve aaaabbbb" in sent[0]


class TestApprovalCommands:
    def test_approve_command_resolves_gate(self, tmp_db):
        import backend.services.permission_gate as pg

        gate = FakeGate()
        gate.requests.append(_req("aaaabbbb-1111-2222-3333-444444444444"))
        monkey = pytest.MonkeyPatch()
        monkey.setattr(pg, "_global_gate", gate)
        try:
            gateway = _make(tmp_db, gate)
            reply = gateway.handle_update(
                {"message": {"chat": {"id": 111}, "text": "/approve aaaabbbb"}}
            )
            assert reply is not None
            assert "已批准" in reply
            assert gate.answers == [("aaaabbbb-1111-2222-3333-444444444444", True)]
        finally:
            monkey.undo()

    def test_deny_command(self, tmp_db):
        import backend.services.permission_gate as pg

        gate = FakeGate()
        gate.requests.append(_req("ccccdddd-1111-2222-3333-444444444444", tool="rm"))
        monkey = pytest.MonkeyPatch()
        monkey.setattr(pg, "_global_gate", gate)
        try:
            gateway = _make(tmp_db, gate)
            reply = gateway.handle_update(
                {"message": {"chat": {"id": 111}, "text": "/deny ccccdddd"}}
            )
            assert "已拒绝" in reply
            assert gate.answers == [("ccccdddd-1111-2222-3333-444444444444", False)]
        finally:
            monkey.undo()

    def test_unknown_short_id(self, tmp_db):
        import backend.services.permission_gate as pg

        gate = FakeGate()
        monkey = pytest.MonkeyPatch()
        monkey.setattr(pg, "_global_gate", gate)
        try:
            gateway = _make(tmp_db, gate)
            reply = gateway.handle_update(
                {"message": {"chat": {"id": 111}, "text": "/approve zzzzzzzz"}}
            )
            assert "未找到" in reply
        finally:
            monkey.undo()

    def test_pending_listing(self, tmp_db):
        import backend.services.permission_gate as pg

        gate = FakeGate()
        gate.requests.append(_req("aaaabbbb-1111-2222-3333-444444444444"))
        monkey = pytest.MonkeyPatch()
        monkey.setattr(pg, "_global_gate", gate)
        try:
            gateway = _make(tmp_db, gate)
            reply = gateway.handle_update(
                {"message": {"chat": {"id": 111}, "text": "/pending"}}
            )
            assert "待审批" in reply
            assert "aaaabbbb" in reply
            assert "bash" in reply
        finally:
            monkey.undo()

    def test_command_bypasses_llm(self, tmp_db):
        """审批命令不进 LLM 对话（llm_factory 不被调用）"""
        import backend.services.permission_gate as pg

        gate = FakeGate()
        gate.requests.append(_req("aaaabbbb-1111-2222-3333-444444444444"))
        llm_called = {"n": 0}

        def factory(sid):
            llm_called["n"] += 1

        config = TelegramConfig(
            bot_token="tok", allowed_chat_ids=["111"], poll_timeout_seconds=0
        )
        gateway = TelegramGateway(
            config=config,
            transport=FakeTransport(),
            llm_factory=factory,
            db=tmp_db,
        )
        monkey = pytest.MonkeyPatch()
        monkey.setattr(pg, "_global_gate", gate)
        try:
            gateway.handle_update(
                {"message": {"chat": {"id": 111}, "text": "/pending"}}
            )
        finally:
            monkey.undo()
        assert llm_called["n"] == 0
