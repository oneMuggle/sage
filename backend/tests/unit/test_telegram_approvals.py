"""Telegram 审批转发与命令测试（Round 10 / 12 补充命令）

gate 替身通过 monkeypatch fixture 注入 —— 断言失败也会自动恢复
_global_gate，杜绝跨文件污染（此前手动 MonkeyPatch 在失败路径
不 undo，曾污染 test_agent_tool_loop 的 get_permission_gate）。
"""

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
    """与 ApprovalGate 同接口的最小替身（补 request —— 老版污染源已修）"""

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

    async def request(self, req, timeout=None):
        self.answers.append((req.request_id, True))
        return SimpleNamespace(approved=True, remember=False, answered_by="test")


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


@pytest.fixture()
def gateway(tmp_db, monkeypatch):
    """网关 + 已注入 FakeGate 的全局闸口（自动恢复）"""
    import backend.services.permission_gate as pg

    gate = FakeGate()
    monkeypatch.setattr(pg, "_global_gate", gate)
    config = TelegramConfig(
        bot_token="tok", allowed_chat_ids=["111"], poll_timeout_seconds=0
    )
    gw = TelegramGateway(
        config=config,
        transport=FakeTransport(),
        llm_factory=lambda sid: None,
        db=tmp_db,
    )
    return gw, gate


class TestApprovalForwarding:
    def test_new_pending_forwarded_once(self, gateway):
        gw, gate = gateway
        gate.requests.append(_req("aaaabbbb-1111-2222-3333-444444444444"))
        gw.transport.updates = []  # 无消息也触发转发
        gw.poll_once()
        gw.poll_once()
        sent = [t for _, t in gw.transport.sent]
        assert sum("待审批" in t for t in sent) == 1  # 去重
        assert "/approve aaaabbbb" in sent[0]


class TestApprovalCommands:
    def test_approve_command_resolves_gate(self, gateway):
        gw, gate = gateway
        gate.requests.append(_req("aaaabbbb-1111-2222-3333-444444444444"))
        reply = gw.handle_update(
            {"message": {"chat": {"id": 111}, "text": "/approve aaaabbbb"}}
        )
        assert reply is not None
        assert "已批准" in reply
        assert gate.answers == [("aaaabbbb-1111-2222-3333-444444444444", True)]

    def test_deny_command(self, gateway):
        gw, gate = gateway
        gate.requests.append(_req("ccccdddd-1111-2222-3333-444444444444", tool="rm"))
        reply = gw.handle_update(
            {"message": {"chat": {"id": 111}, "text": "/deny ccccdddd"}}
        )
        assert "已拒绝" in reply
        assert gate.answers == [("ccccdddd-1111-2222-3333-444444444444", False)]

    def test_unknown_short_id(self, gateway):
        gw, _ = gateway
        reply = gw.handle_update(
            {"message": {"chat": {"id": 111}, "text": "/approve zzzzzzzz"}}
        )
        assert "未找到" in reply

    def test_pending_listing(self, gateway):
        gw, gate = gateway
        gate.requests.append(_req("aaaabbbb-1111-2222-3333-444444444444"))
        reply = gw.handle_update(
            {"message": {"chat": {"id": 111}, "text": "/pending"}}
        )
        assert "待审批" in reply
        assert "aaaabbbb" in reply
        assert "bash" in reply

    def test_command_bypasses_llm(self, gateway):
        """审批命令不进 LLM 对话（llm_factory 不被调用）"""
        llm_called = {"n": 0}
        gw, gate = gateway
        gate.requests.append(_req("aaaabbbb-1111-2222-3333-444444444444"))

        def factory(sid):
            llm_called["n"] += 1

        gw._llm_factory = factory
        gw.handle_update({"message": {"chat": {"id": 111}, "text": "/pending"}})
        assert llm_called["n"] == 0


class TestRound12Commands:
    def test_reset_rebinds_session(self, gateway):
        """/reset 解绑并新建会话 —— 新消息进新会话"""
        gw, _ = gateway
        gw.handle_update({"message": {"chat": {"id": 111}, "text": "第一条"}})
        old_row = gw._conn().execute(
            "SELECT session_id FROM telegram_chats WHERE chat_id = '111'"
        ).fetchone()
        old_sid = old_row[0]

        reply = gw.handle_update({"message": {"chat": {"id": 111}, "text": "/reset"}})
        assert "会话已重置" in reply
        new_row = gw._conn().execute(
            "SELECT session_id FROM telegram_chats WHERE chat_id = '111'"
        ).fetchone()
        assert new_row[0] != old_sid

        gw.handle_update({"message": {"chat": {"id": 111}, "text": "第二条"}})
        old_count = gw._conn().execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (old_sid,)
        ).fetchone()[0]
        assert old_count == 2  # 旧会话不再增长（首条 user+assistant）

    def test_help_lists_commands(self, gateway):
        gw, _ = gateway
        reply = gw.handle_update({"message": {"chat": {"id": 111}, "text": "/help"}})
        assert "/approve" in reply
        assert "/reset" in reply

    def test_unknown_command_shows_help_hint(self, gateway):
        gw, _ = gateway
        reply = gw.handle_update(
            {"message": {"chat": {"id": 111}, "text": "/frobnicate"}}
        )
        assert "未知命令" in reply
        assert "/help" in reply
