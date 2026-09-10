"""Telegram 网关 MVP 单元测试（Round 6）

transport 全部注入 fake —— 零真实外发。
"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest

from backend.data.database import Database
from backend.gateway.telegram import (
    TelegramConfig,
    TelegramGateway,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
    # Gateway 内部的 MessageRepository/SessionRepository 走 get_database()
    # 全局单例 —— 按仓库测试惯例绑定临时库
    import backend.data.database as db_mod

    monkeypatch.setattr(db_mod, "_db", db)
    yield db
    db.close()


class FakeTransport:
    def __init__(self):
        self.updates: list = []
        self.sent: list = []
        self.offset_requested: int = -1

    def get_updates(self, offset: int, timeout_seconds: int):
        self.offset_requested = offset
        out = self.updates
        self.updates = []
        return out

    def send_message(self, chat_id: str, text: str):
        self.sent.append((chat_id, text))


def _make_gateway(tmp_db, allowed=("111",), llm_reply="你好，我是 Sage"):
    """构造带 fake transport 与固定 LLM 回复的网关"""
    config = TelegramConfig(
        bot_token="test-token",
        allowed_chat_ids=list(allowed),
        poll_timeout_seconds=0,
    )
    transport = FakeTransport()

    def fake_llm_factory(session_id):
        class FakeClient:
            async def chat(self, messages):
                return SimpleNamespace(content=llm_reply)

        return FakeClient()

    gateway = TelegramGateway(
        config=config, transport=transport, llm_factory=fake_llm_factory, db=tmp_db
    )
    return gateway, transport


class TestWhitelist:
    def test_unauthorized_chat_rejected_once(self, tmp_db):
        gateway, transport = _make_gateway(tmp_db, allowed=("111",))
        reply = gateway.handle_update(
            {"message": {"chat": {"id": 999}, "text": "hi"}}
        )
        assert reply == "unauthorized"
        assert transport.sent
        assert "未授权" in transport.sent[0][1]
        assert gateway.stats.rejected == 1

    def test_authorized_chat_gets_reply(self, tmp_db):
        gateway, transport = _make_gateway(tmp_db)
        reply = gateway.handle_update(
            {"message": {"chat": {"id": 111}, "text": "你好"}}
        )
        assert reply == "你好，我是 Sage"
        assert transport.sent == [("111", "你好，我是 Sage")]
        assert gateway.stats.messages_replied == 1


class TestSessionBinding:
    def test_first_message_creates_bound_session(self, tmp_db):
        gateway, _ = _make_gateway(tmp_db)
        gateway.handle_update({"message": {"chat": {"id": 111}, "text": "第一条"}})
        row = tmp_db.get_connection().execute(
            "SELECT session_id FROM telegram_chats WHERE chat_id = '111'"
        ).fetchone()
        assert row is not None
        # 新会话存在且落了两条消息（user + assistant）
        msgs = tmp_db.get_connection().execute(
            "SELECT role FROM messages WHERE session_id = ? ORDER BY created_at",
            (row[0],),
        ).fetchall()
        assert [r[0] for r in msgs] == ["user", "assistant"]

    def test_second_message_reuses_session(self, tmp_db):
        gateway, _ = _make_gateway(tmp_db)
        gateway.handle_update({"message": {"chat": {"id": 111}, "text": "一"}})
        gateway.handle_update({"message": {"chat": {"id": 111}, "text": "二"}})
        rows = tmp_db.get_connection().execute(
            "SELECT COUNT(*) FROM telegram_chats WHERE chat_id = '111'"
        ).fetchone()
        assert rows[0] == 1


class TestPollOnce:
    def test_offset_advances_and_drains(self, tmp_db):
        gateway, transport = _make_gateway(tmp_db)
        transport.updates = [
            {"update_id": 10, "message": {"chat": {"id": 111}, "text": "a"}},
            {"update_id": 11, "message": {"chat": {"id": 111}, "text": "b"}},
        ]
        assert gateway.poll_once() == 2
        assert gateway.offset == 12
        # offset 已推进 —— 下一轮 getUpdates 不再拿到旧 update
        assert gateway.poll_once() == 0

    def test_single_bad_update_does_not_break_poll(self, tmp_db):
        gateway, transport = _make_gateway(tmp_db)
        transport.updates = [{"update_id": 1}]  # 无 message —— handle 跳过
        assert gateway.poll_once() == 1
        assert gateway.stats.errors == 0


class TestConfigFromEnv:
    def test_none_without_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        assert TelegramConfig.from_env() is None

    def test_parsed_with_token_and_allowlist(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "1, 2 ,3")
        config = TelegramConfig.from_env()
        assert config is not None
        assert config.enabled
        assert config.allowed_chat_ids == [
            "1",
            "2",
            "3",
        ]

    def test_gateway_singleton_none_without_token(self, monkeypatch):
        from backend.gateway.telegram import (
            get_telegram_gateway,
            reset_telegram_gateway,
        )

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        reset_telegram_gateway()
        assert get_telegram_gateway() is None
