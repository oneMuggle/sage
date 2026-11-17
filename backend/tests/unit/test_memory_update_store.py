"""记忆存储层 title 与 update 行为测试（2026-11-17 记忆详情化）。

覆盖：
- save() 缺省 title 时按内容确定性生成；显式 title 原样落库；
- update() 更新内容/标题/标签，summary 重算、FTS 同步（新词可检索）；
- 不存在/已失效行 update() 返回 False。
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.memory.semantic import SemanticMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


@pytest.fixture()
def episodic(tmp_db_path: str) -> EpisodicMemory:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return EpisodicMemory(db)


@pytest.fixture()
def semantic(tmp_db_path: str) -> SemanticMemory:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return SemanticMemory(db)


class TestEpisodicTitle:
    def test_save_generates_title_from_content(self, episodic: EpisodicMemory) -> None:
        mid = episodic.save("用户偏好函数式编程\n详细说明……", importance=6)
        row = episodic.get_by_id(mid)
        assert row is not None
        assert row["title"] == "用户偏好函数式编程"

    def test_save_keeps_explicit_title(self, episodic: EpisodicMemory) -> None:
        mid = episodic.save("任意内容", importance=5, title="自定义标题")
        row = episodic.get_by_id(mid)
        assert row is not None
        assert row["title"] == "自定义标题"

    def test_save_blank_title_falls_back_to_derived(
        self, episodic: EpisodicMemory
    ) -> None:
        mid = episodic.save("项目使用 uv 管理依赖", importance=5, title="   ")
        row = episodic.get_by_id(mid)
        assert row is not None
        assert row["title"] == "项目使用 uv 管理依赖"


class TestEpisodicUpdate:
    def test_update_content_refreshes_title_and_summary(
        self, episodic: EpisodicMemory
    ) -> None:
        mid = episodic.save("user prefers tea", importance=5)
        assert episodic.update(mid, content="user prefers coffee") is True

        row = episodic.get_by_id(mid)
        assert row is not None
        assert row["content"] == "user prefers coffee"
        assert row["title"] == "user prefers coffee"
        assert "coffee" in row["summary"]

    def test_update_title_only(self, episodic: EpisodicMemory) -> None:
        mid = episodic.save("user prefers tea", importance=5)
        assert episodic.update(mid, title="饮品偏好") is True
        row = episodic.get_by_id(mid)
        assert row is not None
        assert row["title"] == "饮品偏好"
        # 内容未变
        assert row["content"] == "user prefers tea"

    def test_update_refreshes_fts_index(self, episodic: EpisodicMemory) -> None:
        mid = episodic.save("user prefers tea", importance=5)
        episodic.update(mid, content="user prefers coffee")
        hits = episodic.search("coffee", limit=5)
        assert any(h["id"] == mid for h in hits)
        # 旧内容不应再命中（FTS 行已重建）
        old_hits = episodic.search("tea", limit=5)
        assert all(h["id"] != mid for h in old_hits)

    def test_update_tags_and_importance(self, episodic: EpisodicMemory) -> None:
        mid = episodic.save("user prefers tea", importance=5)
        assert (
            episodic.update(mid, tags=["drinks", "preference"], importance=9) is True
        )
        row = episodic.get_by_id(mid)
        assert row is not None
        assert row["importance"] == 9
        assert "drinks" in row["tags"]

    def test_update_missing_id_returns_false(self, episodic: EpisodicMemory) -> None:
        assert episodic.update("no-such-id", content="x") is False


class TestSemanticTitleAndUpdate:
    def test_save_generates_title(self, semantic: SemanticMemory) -> None:
        mid = semantic.save("Python 是解释型编程语言")
        row = semantic.get_by_id(mid)
        assert row is not None
        assert row["title"] == "Python 是解释型编程语言"

    def test_update_content_regenerates_title(self, semantic: SemanticMemory) -> None:
        mid = semantic.save("Python 是解释型编程语言")
        assert semantic.update(mid, content="Rust 是编译型系统语言") is True
        row = semantic.get_by_id(mid)
        assert row is not None
        assert row["content"] == "Rust 是编译型系统语言"
        assert row["title"] == "Rust 是编译型系统语言"

    def test_update_missing_id_returns_false(self, semantic: SemanticMemory) -> None:
        assert semantic.update("no-such-id", content="x") is False


def test_episodic_update_respects_session_foreign_key(
    episodic: EpisodicMemory,
) -> None:
    # update 不应破坏既有 session 关联
    ensure_session(episodic.db, "sess-update")
    mid = episodic.save("user prefers tea", session_id="sess-update", importance=5)
    assert episodic.update(mid, content="user prefers coffee") is True
    row = episodic.get_by_id(mid)
    assert row is not None
    assert row["session_id"] == "sess-update"
