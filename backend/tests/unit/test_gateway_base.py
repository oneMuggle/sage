"""Gateway Base 抽象基类测试（Round 17）

用最小子类验证抽象点契约：实现 fetch_updates / send_reply /
parse_update / allowed_chat_ids 四个平台点即可驱动完整
「轮询 → 命令 → LLM 对话 → 审批转发」流程。
"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest

from backend.gateway.base import BaseGateway, GatewayStats, history_budget

pytestmark = pytest.mark.unit


class MinimalGateway(BaseGateway):
    """四平台点 + 最小配置的最小子类"""

    event_id_key = "seq"
    allowed = ["111"]

    def __init__(self, tmp_db, llm_reply="ok"):
        super().__init__(llm_factory=lambda sid: _FakeLLM(llm_reply), db=tmp_db)
        self.updates: list = []
        self.sent: list = []

    def fetch_updates(self):
        out = self.updates
        self.updates = []
        return out

    def send_reply(self, chat_id, text):
        self.sent.append((chat_id, text))

    def parse_update(self, update):
        cid = str(update.get("cid", ""))
        text = (update.get("text") or "").strip()
        if not cid or not text:
            return None
        return cid, text

    @property
    def allowed_chat_ids(self):
        return self.allowed


class _FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    async def chat(self, messages):
        return SimpleNamespace(content=self.reply)


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


class TestMinimalSubclassContract:
    def test_full_flow_via_abstract_points(self, tmp_db):
        """实现四平台点即可驱动：轮询 → 白名单 → LLM → 回复"""
        gw = MinimalGateway(tmp_db)
        gw.updates = [{"seq": 1, "cid": "111", "text": "hello"}]
        assert gw.poll_once() == 1
        assert gw.offset == 2
        assert gw.sent == [("111", "ok")]

    def test_command_flow_via_abstract_points(self, tmp_db):
        gw = MinimalGateway(tmp_db)
        reply = gw.process_message("111", "/help")
        assert "/approve" in reply

    def test_stats_type_shared(self):
        assert isinstance(GatewayStats(), GatewayStats)

    def test_history_context_excludes_compacted_rows(self, tmp_db):
        """2026-11-05 非破坏压缩：网关拼历史时不得回放压缩展示行。"""
        from backend.data.session_repo import Message, MessageRepository

        captured: dict = {}

        class _CapturingLLM:
            async def chat(self, messages):
                captured["messages"] = messages
                return SimpleNamespace(content="ok")

        gw = MinimalGateway(tmp_db)
        gw._llm_factory = lambda sid: _CapturingLLM()
        sid = gw._session_for_chat("111")
        repo = MessageRepository()
        repo.save(
            Message(
                id="old-1",
                session_id=sid,
                role="user",
                content="压缩前的旧消息",
                created_at=1700000000000,
                compacted_at=1700000005000,
            )
        )
        repo.save(
            Message(
                id="new-1",
                session_id=sid,
                role="assistant",
                content="保留的新消息",
                created_at=1700000001000,
            )
        )

        gw.process_message("111", "hello")

        contents = [m["content"] for m in captured["messages"]]
        assert "压缩前的旧消息" not in contents
        assert "保留的新消息" in contents
        assert "hello" in contents


class TestHistoryBudget:
    def test_short_history_untouched(self):
        msgs = [SimpleNamespace(role="user", content=f"m{i}") for i in range(3)]
        kept, omitted = history_budget(msgs)
        assert kept == msgs
        assert omitted == 0

    def test_budget_disabled(self, monkeypatch):
        monkeypatch.setenv("SAGE_GW_HISTORY_TOKEN_BUDGET", "0")
        msgs = [SimpleNamespace(role="user", content="x" * 500) for _ in range(6)]
        kept, omitted = history_budget(msgs)
        assert len(kept) == 6
        assert omitted == 0
