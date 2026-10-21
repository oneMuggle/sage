"""自动标签派生（auto_tag）单元 + 集成测试。

覆盖：
- ``derive_tags``：jieba 分词 → 过滤 → 加权排序 → top N
- ``normalize_tags``：list / JSON 字符串 / None / 非 list 的规整
- ``is_valid_tag`` / ``filter_valid_tags``：长度、停用词、纯数字、纯标点
- 存储侧集成：episodic / semantic 的 ``save()`` 无标签时自动派生
- 图谱侧集成：无标签的存量记忆也能进入 ``TagCooccurrenceGraph``
- 词表一致性：存储派生的标签必然能被查询侧 ``_extract_query_tags`` 命中
"""

from __future__ import annotations

import json

import pytest

from backend.adapters.out.memory.adapter import _extract_query_tags
from backend.data.database import Database
from backend.memory.auto_tag import (
    TAG_STOPWORDS,
    derive_tags,
    filter_valid_tags,
    is_valid_tag,
    normalize_tags,
)
from backend.memory.episodic import EpisodicMemory
from backend.memory.semantic import SemanticMemory
from backend.memory.tag_graph import TagCooccurrenceGraph
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# derive_tags
# ---------------------------------------------------------------------------


class TestDeriveTags:
    def test_derives_meaningful_tags_from_chinese_content(self):
        tags = derive_tags("用户喜欢 Python 编程")
        assert "Python" in tags
        assert len(tags) >= 1

    def test_excludes_stopwords(self):
        tags = derive_tags("这个用户是在处理相关的内容信息")
        for sw in TAG_STOPWORDS:
            assert sw not in tags

    def test_returns_empty_for_content_without_valid_tokens(self):
        assert derive_tags("短内容") == []
        assert derive_tags("x") == []
        assert derive_tags("") == []
        assert derive_tags("   ") == []

    def test_respects_max_tags(self):
        content = "研发传感器校准流程涉及试验排期与风险项闭环"
        assert len(derive_tags(content, max_tags=2)) == 2
        assert len(derive_tags(content, max_tags=0)) == 0

    def test_is_deterministic(self):
        content = "团队每周一上午召开研发同步会，关注传感器研发进度。"
        assert derive_tags(content) == derive_tags(content)

    def test_prefers_frequent_and_longer_tokens(self):
        tags = derive_tags("研发 研发 研发 传感器")
        assert tags[0] == "研发"

    def test_keeps_english_tokens(self):
        tags = derive_tags("smoke test for docker pipeline", max_tags=5)
        assert "smoke" in tags
        assert "test" in tags
        assert "docker" in tags


# ---------------------------------------------------------------------------
# normalize_tags
# ---------------------------------------------------------------------------


class TestNormalizeTags:
    def test_none_returns_empty(self):
        assert normalize_tags(None) == []

    def test_list_is_kept_and_deduped(self):
        assert normalize_tags(["a", "b", "a"]) == ["a", "b"]

    def test_json_string_is_parsed(self):
        assert normalize_tags('["x", "y"]') == ["x", "y"]

    def test_invalid_json_string_returns_empty(self):
        assert normalize_tags("not json") == []

    def test_non_list_returns_empty(self):
        assert normalize_tags(42) == []
        assert normalize_tags({"a": 1}) == []

    def test_strips_whitespace_and_drops_empty(self):
        assert normalize_tags(["  a  ", "", "   "]) == ["a"]

    def test_non_string_items_are_dropped(self):
        assert normalize_tags(["a", 1, None, "b"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# is_valid_tag / filter_valid_tags
# ---------------------------------------------------------------------------


class TestIsValidTag:
    def test_rejects_short_token(self):
        assert is_valid_tag("短") is False

    def test_rejects_stopword(self):
        assert is_valid_tag("的") is False
        assert is_valid_tag("用户") is False

    def test_rejects_pure_digits(self):
        assert is_valid_tag("2026") is False

    def test_rejects_punctuation(self):
        assert is_valid_tag("——") is False

    def test_accepts_real_tag(self):
        assert is_valid_tag("传感器") is True


class TestFilterValidTags:
    def test_filters_and_preserves_order(self):
        assert filter_valid_tags(["研发", "的", "2026", "传感器"]) == ["研发", "传感器"]


# ---------------------------------------------------------------------------
# 词表一致性：存储派生 ↔ 查询抽取
# ---------------------------------------------------------------------------


class TestVocabularyConsistency:
    def test_derived_tags_are_query_extractable(self):
        """存储侧派生的标签必须能被查询侧抽到——否则图谱两端对不上。"""
        content = "团队每周一上午召开研发同步会，关注传感器研发进度。"
        derived = derive_tags(content)
        query_tags = _extract_query_tags(content)
        for tag in derived:
            assert tag in query_tags

    def test_derived_tags_survive_shared_filter(self):
        content = "研发 传感器 校准 流程"
        derived = set(derive_tags(content))
        filtered = set(filter_valid_tags(derived))
        assert derived == filtered

    def test_query_tags_superset_storage_tags(self):
        """同一段文本：查询标签（上限 5）⊇ 存储标签（上限 3）。"""
        content = "团队每周一上午召开研发同步会，关注传感器研发进度与试验排期。"
        assert set(derive_tags(content)).issubset(set(_extract_query_tags(content)))

    def test_query_tags_contain_no_invalid_token(self):
        """查询侧不得产出停用词/单字/纯数字/纯标点。"""
        tags = _extract_query_tags("用户是在 2026 年 使用 Python 和 FastAPI 的")
        for tag in tags:
            assert is_valid_tag(tag)


# ---------------------------------------------------------------------------
# 存储侧集成
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db_path: str) -> Database:
    database = Database(db_path=tmp_db_path)
    database.init_db()
    return database


class TestStorageLayerDerivation:
    def test_episodic_save_derives_tags_when_missing(self, db):
        episodic = EpisodicMemory(db)
        ensure_session(db, "s1")
        memory_id = episodic.save("团队召开研发同步会，关注传感器研发进度", session_id="s1")

        stored = json.loads(
            db.get_connection()
            .execute("SELECT tags FROM memories_episodic WHERE id = ?", (memory_id,))
            .fetchone()["tags"]
        )
        assert stored, "无显式标签时应自动派生标签"
        assert "研发" in stored

    def test_episodic_explicit_tags_win(self, db):
        episodic = EpisodicMemory(db)
        ensure_session(db, "s1")
        memory_id = episodic.save(
            "团队召开研发同步会，关注传感器研发进度",
            session_id="s1",
            metadata={"tags": ["显式标签"]},
        )

        stored = json.loads(
            db.get_connection()
            .execute("SELECT tags FROM memories_episodic WHERE id = ?", (memory_id,))
            .fetchone()["tags"]
        )
        assert stored == ["显式标签"]

    def test_semantic_save_derives_tags_when_missing(self, db):
        semantic = SemanticMemory(db)
        memory_id = semantic.save("团队召开研发同步会，关注传感器研发进度")

        stored = json.loads(
            db.get_connection()
            .execute("SELECT tags FROM memories_semantic WHERE id = ?", (memory_id,))
            .fetchone()["tags"]
        )
        assert stored, "无显式标签时应自动派生标签"

    def test_semantic_explicit_tags_win(self, db):
        semantic = SemanticMemory(db)
        memory_id = semantic.save("团队召开研发同步会", tags=["显式标签"])

        stored = json.loads(
            db.get_connection()
            .execute("SELECT tags FROM memories_semantic WHERE id = ?", (memory_id,))
            .fetchone()["tags"]
        )
        assert stored == ["显式标签"]

    def test_content_without_valid_tokens_keeps_empty_tags(self, db):
        semantic = SemanticMemory(db)
        memory_id = semantic.save("短内容")
        stored = json.loads(
            db.get_connection()
            .execute("SELECT tags FROM memories_semantic WHERE id = ?", (memory_id,))
            .fetchone()["tags"]
        )
        assert stored == []


# ---------------------------------------------------------------------------
# 图谱侧集成：存量无标签记忆也要能进图
# ---------------------------------------------------------------------------


class TestTagGraphDerivation:
    def _insert_legacy_row(self, db, table: str, memory_id: str, content: str) -> None:
        conn = db.get_connection()
        if table == "memories_episodic":
            conn.execute(
                "INSERT INTO memories_episodic "
                "(id, content, summary, importance, tags, created_at, is_valid) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (memory_id, content, content, 5, "[]", 1000),
            )
        else:
            conn.execute(
                "INSERT INTO memories_semantic "
                "(id, content, summary, tags, session_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (memory_id, content, content, "[]", "default", 1000),
            )
        conn.commit()

    def test_tagless_legacy_memory_enters_graph(self, db):
        """存量 tags=[] 的记忆此前对图谱完全不可见——修复后应能入图。"""
        episodic = EpisodicMemory(db)
        semantic = SemanticMemory(db)
        self._insert_legacy_row(
            db, "memories_episodic", "legacy-1", "团队召开研发同步会，关注传感器研发进度"
        )
        self._insert_legacy_row(
            db, "memories_semantic", "legacy-2", "研发流程包含传感器校准与试验排期"
        )

        graph = TagCooccurrenceGraph()
        graph.build_from_memories(episodic, semantic)

        assert graph.total_memories == 2
        assert "研发" in graph.tag_memory_index
        assert "legacy-1" in graph.tag_memory_index["研发"]

    def test_explicit_tags_take_precedence_over_derived(self, db):
        episodic = EpisodicMemory(db)
        semantic = SemanticMemory(db)
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO memories_episodic "
            "(id, content, summary, importance, tags, created_at, is_valid) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (
                "legacy-3",
                "团队召开研发同步会",
                "团队召开研发同步会",
                5,
                json.dumps(["显式标签"], ensure_ascii=False),
                1000,
            ),
        )
        conn.commit()

        graph = TagCooccurrenceGraph()
        graph.build_from_memories(episodic, semantic)

        assert "显式标签" in graph.tag_memory_index
        assert "legacy-3" in graph.tag_memory_index["显式标签"]
        assert "legacy-3" not in graph.tag_memory_index.get("研发", set())
