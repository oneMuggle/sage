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
        assert self.task._parse_preference_json(raw) == (
            {"response_length": "short", "tone": "formal"},
            [],
        )

    def test_fenced_json_with_prose(self):
        raw = '好的，以下是提取结果：\n```json\n{"detail_level": "comprehensive"}\n```'
        assert self.task._parse_preference_json(raw) == (
            {"detail_level": "comprehensive"},
            [],
        )

    def test_garbage_returns_empty(self):
        assert self.task._parse_preference_json("不是 JSON") == ({}, [])
        assert self.task._parse_preference_json("") == ({}, [])
        assert self.task._parse_preference_json("[1,2,3]") == ({}, [])

    def test_disallowed_values_filtered(self):
        raw = '{"response_length": "超长", "tone": "klingon", "detail_level": "brief"}'
        assert self.task._parse_preference_json(raw) == ({"detail_level": "brief"}, [])

    def test_new_dimensions_accepted(self):
        """Task 2.3 —— 新加的 3 个维度（code_style / comment_preference /
        explanation_depth）必须通过 parser 白名单。"""
        raw = (
            '{"code_style": "functional", "comment_preference": "detailed", '
            '"explanation_depth": "detailed"}'
        )
        assert self.task._parse_preference_json(raw) == (
            {
                "code_style": "functional",
                "comment_preference": "detailed",
                "explanation_depth": "detailed",
            },
            [],
        )

    def test_invalid_new_dimension_value_filtered(self):
        """新维度的非法取值仍要被过滤掉。"""
        raw = '{"code_style": "procedural", "comment_preference": "verbose"}'
        assert self.task._parse_preference_json(raw) == ({}, [])


class TestParsePreferenceJsonFreeText:
    """Task 2.3 —— 自由文本偏好（枚举维度覆盖不了的具体要求）。"""

    def setup_method(self):
        self.task = PreferenceLearningTask.__new__(PreferenceLearningTask)

    def test_nested_format_returns_structured_and_free_text(self):
        raw = (
            '{"structured": {"response_length": "short"}, '
            '"free_text": [{"category": "注释", "preference": "关键函数需要 docstring"}]}'
        )
        structured, free_text = self.task._parse_preference_json(raw)
        assert structured == {"response_length": "short"}
        assert free_text == [
            {"category": "注释", "preference": "关键函数需要 docstring"}
        ]

    def test_flat_format_backward_compatible(self):
        """旧 prompt / 保守模型输出扁平 JSON 时仍能解析（无 free_text）。"""
        structured, free_text = self.task._parse_preference_json(
            '{"response_length": "short"}'
        )
        assert structured == {"response_length": "short"}
        assert free_text == []

    def test_free_text_missing_fields_dropped(self):
        raw = (
            '{"structured": {}, "free_text": ['
            '{"category": "注释"}, '
            '{"preference": "只有内容"}, '
            '{"category": "", "preference": "空分类"}, '
            '{"category": "x", "preference": ""}'
            "]}"
        )
        structured, free_text = self.task._parse_preference_json(raw)
        assert structured == {}
        assert free_text == []

    def test_free_text_non_dict_items_ignored(self):
        raw = '{"structured": {}, "free_text": ["字符串", 123, null]}'
        _, free_text = self.task._parse_preference_json(raw)
        assert free_text == []

    def test_free_text_truncated(self):
        """超长 category / preference 会被截断，避免污染画像快照。"""
        long_cat = "类" * 40
        long_pref = "偏" * 300
        raw = (
            '{"structured": {}, "free_text": '
            f'[{{"category": "{long_cat}", "preference": "{long_pref}"}}]}}'
        )
        _, free_text = self.task._parse_preference_json(raw)
        assert len(free_text) == 1
        assert len(free_text[0]["category"]) == 20
        assert len(free_text[0]["preference"]) == 120


class TestKeywordAnalysis:
    """``_analyze_preferences`` 关键词路径（LLM 不可用时的降级路）。"""

    def test_new_dimensions_detected_by_keyword(self):
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        result = task._analyze_preferences(
            [
                {"content": "我希望代码用函数式写"},
                {"content": "关键函数加详细注释"},
                {"content": "直接给答案就行，不用详细推导"},
            ]
        )
        assert result["code_style"] == "functional"
        assert result["comment_preference"] == "detailed"
        assert result["explanation_depth"] == "direct"

    def test_no_signal_returns_empty(self):
        """无关键词信号时不返回任何维度。

        回归：早期实现会填入 3 个默认值，导致 ``preferences`` 表的
        ``ON CONFLICT DO UPDATE`` 用默认值覆盖用户此前学到的偏好。
        """
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        result = task._analyze_preferences([{"content": "今天天气真不错"}])
        assert result == {}


class TestAnalyzeWithLLM:
    @pytest.mark.asyncio()
    async def test_llm_returns_preferences(self):
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        llm = MagicMock()
        llm.chat = AsyncMock(return_value='{"response_length": "short"}')
        messages = [{"content": "回答简短点"}, {"content": "今天天气如何"}]
        structured, free_text = await task._analyze_preferences_with_llm(llm, messages)
        assert structured == {"response_length": "short"}
        assert free_text == []

    @pytest.mark.asyncio()
    async def test_llm_returns_free_text(self):
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        llm = MagicMock()
        llm.chat = AsyncMock(
            return_value=(
                '{"structured": {"code_style": "functional"}, '
                '"free_text": [{"category": "注释", "preference": "关键函数需要 docstring"}]}'
            )
        )
        structured, free_text = await task._analyze_preferences_with_llm(
            llm, [{"content": "别用 class，关键函数加 docstring"}]
        )
        assert structured == {"code_style": "functional"}
        assert free_text == [
            {"category": "注释", "preference": "关键函数需要 docstring"}
        ]

    @pytest.mark.asyncio()
    async def test_llm_failure_returns_empty(self):
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=RuntimeError("endpoint down"))
        result = await task._analyze_preferences_with_llm(llm, [{"content": "hi"}])
        assert result == ({}, [])

    @pytest.mark.asyncio()
    async def test_empty_messages_skips_llm(self):
        task = PreferenceLearningTask.__new__(PreferenceLearningTask)
        llm = MagicMock()
        llm.chat = AsyncMock()
        result = await task._analyze_preferences_with_llm(llm, [])
        assert result == ({}, [])
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
        assert "简短" in sem[0]  # 偏好值已翻译为中文标签
        pref = conn.execute(
            "SELECT value FROM preferences WHERE key = 'pref_response_length'"
        ).fetchone()
        assert pref is not None
        assert pref[0] == "short"

    @pytest.mark.asyncio()
    async def test_free_text_preference_persisted(self, tmp_db, monkeypatch):
        """Task 2.3 —— 自由文本偏好落语义记忆 + user_profile。"""
        _insert_user_message(tmp_db, "别用 class，关键函数加 docstring")
        task = PreferenceLearningTask(db=tmp_db, llm_client=None, config={})
        fake_llm = MagicMock()
        fake_llm.chat = AsyncMock(
            return_value=(
                '{"structured": {"code_style": "functional"}, '
                '"free_text": [{"category": "注释", "preference": "关键函数需要 docstring"}]}'
            )
        )
        monkeypatch.setattr(task, "_resolve_llm", lambda: fake_llm)

        result = await task.run_async()
        assert result >= 1

        conn = tmp_db.get_connection()
        sem = conn.execute(
            "SELECT content, summary FROM memories_semantic ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert sem is not None
        assert "关键函数需要 docstring" in sem[0]
        assert "关键函数需要 docstring" in sem[1]

        from backend.memory.user_profile import UserProfileStore

        store = UserProfileStore(tmp_db)
        store.load()
        contents = [entry["content"] for entry in store.list()]
        assert any("关键函数需要 docstring" in c for c in contents)

    @pytest.mark.asyncio()
    async def test_free_text_only_still_writes(self, tmp_db, monkeypatch):
        """只有自由文本（无结构化维度）时也应落库。"""
        _insert_user_message(tmp_db, "今天天气真不错")
        task = PreferenceLearningTask(db=tmp_db, llm_client=None, config={})
        fake_llm = MagicMock()
        fake_llm.chat = AsyncMock(
            return_value=(
                '{"structured": {}, '
                '"free_text": [{"category": "回复习惯", "preference": "先给结论再给推导"}]}'
            )
        )
        monkeypatch.setattr(task, "_resolve_llm", lambda: fake_llm)

        result = await task.run_async()
        assert result == 1

        conn = tmp_db.get_connection()
        sem = conn.execute(
            "SELECT content FROM memories_semantic ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert sem is not None
        assert "先给结论再给推导" in sem[0]
