"""网关会话上下文预算测试（Round 11）"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest

from backend.gateway.telegram import TelegramConfig, TelegramGateway, _history_budget

pytestmark = pytest.mark.unit


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


def _msg(role: str, content: str):
    return SimpleNamespace(role=role, content=content)


class TestHistoryBudget:
    def test_short_history_untouched(self):
        history = [_msg("user", f"短消息 {i}") for i in range(5)]
        kept, omitted = _history_budget(history)
        assert kept == history
        assert omitted == 0

    def test_long_history_truncated_with_omitted(self, monkeypatch):
        monkeypatch.setenv("SAGE_GW_HISTORY_TOKEN_BUDGET", "200")
        big = "x" * 2000  # 单条 ~1000 token
        history = [_msg("user", f"msg{i} {big}") for i in range(10)]
        history[-1] = _msg("user", "最新问题")
        kept, omitted = _history_budget(history)
        assert 2 <= len(kept) < 10
        assert omitted == 10 - len(kept)
        # 最新消息必须保留
        assert kept[-1].content == "最新问题"

    def test_budget_disabled_keeps_all(self, monkeypatch):
        monkeypatch.setenv("SAGE_GW_HISTORY_TOKEN_BUDGET", "0")
        big = "x" * 2000
        history = [_msg("user", f"msg{i} {big}") for i in range(10)]
        kept, omitted = _history_budget(history)
        assert len(kept) == 10
        assert omitted == 0

    def test_at_least_two_messages_kept(self, monkeypatch):
        monkeypatch.setenv("SAGE_GW_HISTORY_TOKEN_BUDGET", "10")
        history = [_msg("user", "x" * 3000), _msg("assistant", "y" * 3000)]
        kept, omitted = _history_budget(history)
        assert len(kept) == 2
        assert omitted == 0


class FakeTransport:
    def __init__(self):
        self.sent: list = []

    def get_updates(self, offset, timeout_seconds):
        return []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class TestChatIntegration:
    def test_long_history_injects_omission_note(self, tmp_db, monkeypatch):
        captured = {}

        class FakeClient:
            async def chat(self, messages):
                captured["messages"] = messages
                return SimpleNamespace(content="好的")

        from backend.data.session_repo import Message, MessageRepository

        config = TelegramConfig(
            bot_token="tok", allowed_chat_ids=["111"], poll_timeout_seconds=0
        )
        gateway = TelegramGateway(
            config=config,
            transport=FakeTransport(),
            llm_factory=lambda sid: FakeClient(),
            db=tmp_db,
        )
        monkeypatch.setenv("SAGE_GW_HISTORY_TOKEN_BUDGET", "150")

        repo = MessageRepository()
        session_id = gateway._session_for_chat("111")
        for i in range(8):
            repo.save(
                Message(
                    id=f"m{i}",
                    session_id=session_id,
                    role="user",
                    content=f"问题{i} " + "y" * 400,
                    created_at=1700000000 + i,
                )
            )
        reply = gateway.handle_update(
            {"message": {"chat": {"id": 111}, "text": "最新问题"}}
        )
        assert reply == "好的"
        messages = captured["messages"]
        assert messages[0]["role"] == "system"
        assert "已省略" in messages[0]["content"]
        assert messages[-1]["content"] == "最新问题"
