"""PreferenceLearningTask LLM 路径测试

覆盖:
- _parse_preference_json: 合法 JSON / 代码围栏 / 垃圾输出 / 越界值过滤
- _analyze_preferences_with_llm: LLM 正常返回 / 失败降级
- _resolve_llm: 注入优先
- run_async: 证据门槛（无关键词反馈且 LLM 无信号时不落库）+ LLM 结果落库
"""

from __future__ import annotations

import tempfile
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.data.database import Database
from backend.scheduler.evolution import PreferenceLearningTask

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


def _insert_user_message(db, content: str, created_at: Optional[int] = None) -> None:
    """SAGE 工作流: 手工插入一条用户消息（消息表要求会话存在）"""
    conn = db.get_connection()
    session_id = "sess-pref-test"
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", int(time.time()), int(time.time())),
    )
    conn.execute(
        """INSERT INTO messages (id, session_id, role, content, created_at)
           VALUES (?, ?, 'user', ?, ?)""",
        (f"msg-{content[:8]}", session_id, content, created_at or int(time.time())),
    )
    conn.commit()


class TestParsePreferenceJson:
    def setup_method(self):
        self.task = PreferenceLearningTask.__new__(PreferenceLearningTask)

    def test_valid_json(self):
        raw = '{"response_length": "short", "tone": "formal"}'
        assert self.task._parse_preference_json(raw) == {
            "response_length": "short",
            "tone": "formal",
        }

    def test_fenced_json_with_prose(self):
        raw = '好的，以下是提取结果：\n```json\n{"detail_level": "comprehensive"}\n```'
        assert self.task._parse_preference_json(raw) == {"detail_level": "comprehensive"}

    def test_garbage_returns_empty(self):
        assert self.task._parse_preference_json("不是 JSON") == {}
        assert self.task._parse_preference_json("") == {}
        assert self.task._parse_preference_json("[1,2,3]") == {}

    def test_disallowed_values_filtered(self):
        raw = '{"response_length": "超长", "tone": "klingon", "detail_level": "brief"}'
        assert self.task._parse_preference_json(raw) == {"detail_level": "brief"}


class TestAnalyzeWithLLM:
    @pytest.mark.asyncio()
    async def test_llm_returns_preferences(self):
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        llm = MagicMock()
        llm.chat = AsyncMock(return_value='{"response_length": "short"}')
        messages = [{"content": "回答简短点"}, {"content": "今天天气如何"}]
        result = await task._analyze_preferences_with_llm(llm, messages)
        assert result == {"response_length": "short"}

    @pytest.mark.asyncio()
    async def test_llm_failure_returns_empty(self):
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=RuntimeError("endpoint down"))
        result = await task._analyze_preferences_with_llm(llm, [{"content": "hi"}])
        assert result == {}

    @pytest.mark.asyncio()
    async def test_empty_messages_skips_llm(self):
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        llm = MagicMock()
        llm.chat = AsyncMock()
        result = await task._analyze_preferences_with_llm(llm, [])
        assert result == {}
        llm.chat.assert_not_called()


class TestResolveLLM:
    @pytest.mark.asyncio()
    async def test_injected_client_wins(self, tmp_db, monkeypatch):
        """注入的客户端优先, 不读 settings"""
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        injected = MagicMock()
        task = PreferenceLearningTask(db=tmp_db, llm_client=injected)
        assert task._resolve_llm() is injected


class TestRunAsyncEvidenceGate:
    @pytest.mark.asyncio()
    async def test_no_evidence_no_write(self, tmp_db, monkeypatch):
        """无关键词反馈且 LLM 无信号 → 不写库"""
        _insert_user_message(tmp_db, "今天天气真不错")
        task = PreferenceLearningTask(db=tmp_db, llm_client=None, config={})
        # LLM 解析失败（无端点配置）→ None → 只走关键词路径
        monkeypatch.setattr(task, "_resolve_llm", lambda: None)
        result = await task.run_async()
        assert result == 0
        row = tmp_db.get_connection().execute(
            "SELECT COUNT(*) FROM memories_semantic"
        ).fetchone()
        assert row[0] == 0

    @pytest.mark.asyncio()
    async def test_llm_preferences_persisted(self, tmp_db, monkeypatch):
        """LLM 抽取的偏好覆盖关键词基线并落库"""
        _insert_user_message(tmp_db, "回答简短点")
        task = PreferenceLearningTask(db=tmp_db, llm_client=None, config={})
        fake_llm = MagicMock()
        fake_llm.chat = AsyncMock(return_value='{"response_length": "short"}')
        monkeypatch.setattr(task, "_resolve_llm", lambda: fake_llm)

        result = await task.run_async()
        assert result >= 1

        conn = tmp_db.get_connection()
        sem = conn.execute(
            "SELECT content FROM memories_semantic ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert sem is not None
        assert "short" in sem[0]
        pref = conn.execute(
            "SELECT value FROM preferences WHERE key = 'pref_response_length'"
        ).fetchone()
        assert pref is not None
        assert pref[0] == "short"
