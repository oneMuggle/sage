"""R119 — SemanticMemory（语义记忆 SQLite + FTS5）单元测试。

覆盖：save 默认值与显式字段往返、摘要截断、FTS 主路径检索（中/英文）、
空查询回退 get_recent、LIKE 兜底、session 隔离、tags 过滤、get_recent
排序/limit、get_by_id/exists_by_content、delete 主表+FTS 同步、invalidate
P3 失效语义（检索排除/审计可见/幂等）、count 过滤、update_tags 同步、
scope 轴检索与非法组合短路。
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory.semantic import SemanticMemory
from backend.memory.summary_text import truncate_summary

pytestmark = pytest.mark.unit


@pytest.fixture()
def memory():
    db = Database(db_path=":memory:")
    db.init_db()
    return SemanticMemory(db)


# ---------------------------------------------------------------------------
# save / get_by_id / 摘要
# ---------------------------------------------------------------------------


def test_save_returns_id_and_round_trips(memory):
    mid = memory.save("用户喜欢火锅", summary="摘要", tags=["饮食", "偏好"],
                      session_id="s1")
    got = memory.get_by_id(mid)
    assert got is not None
    assert got["content"] == "用户喜欢火锅"
    assert got["summary"] == "摘要"
    assert got["tags"] == ["饮食", "偏好"]
    assert got["session_id"] == "s1"
    assert got["invalid_at"] is None


def test_save_generates_uuid_and_default_summary(memory):
    mid = memory.save("短内容")
    got = memory.get_by_id(mid)
    assert len(mid) == 36  # uuid4 hex-with-dashes
    assert got["summary"] == "短内容"
    assert got["tags"] == []


def test_save_long_content_summary_truncated(memory):
    content = "字" * 200
    got = memory.get_by_id(memory.save(content))
    assert got["summary"] == truncate_summary(content, 150)
    assert got["summary"].endswith("...")


def test_get_by_id_missing_returns_none(memory):
    assert memory.get_by_id("no-such-id") is None


# ---------------------------------------------------------------------------
# search：FTS 主路径 / 兜底
# ---------------------------------------------------------------------------


def test_search_chinese_hits_via_fts(memory):
    memory.save("用户喜欢火锅", session_id="s1")
    memory.save("完全无关的内容", session_id="s1")
    hits = memory.search("火锅", session_id="s1")
    assert len(hits) == 1
    assert hits[0]["content"] == "用户喜欢火锅"


def test_search_english_hits(memory):
    memory.save("python asyncio tutorial", session_id="s1")
    hits = memory.search("asyncio", session_id="s1")
    assert len(hits) == 1


def test_search_no_match_returns_empty(memory):
    memory.save("完全无关的内容")
    # 纯 ASCII 乱码：分词后单一 token，主表与索引中都不存在
    assert memory.search("zzzymckqvw") == []


def test_search_empty_query_falls_back_to_recent(memory):
    mid1 = memory.save("第一條", session_id="s1")
    mid2 = memory.save("第二條", session_id="s1")
    hits = memory.search("   ", session_id="s1")
    contents = [h["id"] for h in hits]
    assert set(contents) == {mid1, mid2}


def test_search_session_isolation(memory):
    memory.save("用户喜欢火锅", session_id="s1")
    memory.save("火锅底料配方", session_id="s2")
    hits = memory.search("火锅", session_id="s1")
    assert len(hits) == 1
    assert hits[0]["session_id"] == "s1"


def test_search_tags_filter(memory):
    memory.save("带标签的火锅笔记", tags=["饮食"], session_id="s1")
    memory.save("无标签的火锅笔记", session_id="s1")
    hits = memory.search("火锅", tags=["饮食"], session_id="s1")
    assert len(hits) == 1
    assert hits[0]["tags"] == ["饮食"]


# ---------------------------------------------------------------------------
# get_recent / count / exists
# ---------------------------------------------------------------------------


def test_get_recent_ordering_and_limit(memory, monkeypatch):
    # created_at 为毫秒时间戳：同毫秒内三次 save 会并列打乱排序断言，
    # 注入单调递增的假时钟保证严格递增
    from types import SimpleNamespace

    import backend.memory.semantic as sem_mod

    counter = {"ms": 1_000}

    def fake_time():
        counter["ms"] += 50
        return counter["ms"] / 1000.0

    monkeypatch.setattr(sem_mod, "time", SimpleNamespace(time=fake_time))
    ids = [memory.save(f"内容{i}") for i in range(3)]
    recent = memory.get_recent(limit=2)
    assert len(recent) == 2
    # created_at 降序：最后写入的两条
    assert [r["id"] for r in recent] == ids[::-1][:2]


def test_get_recent_session_filter(memory):
    memory.save("甲会话记忆", session_id="s1")
    memory.save("乙会话记忆", session_id="s2")
    recent = memory.get_recent(session_id="s1")
    assert [r["session_id"] for r in recent] == ["s1"]


def test_exists_by_content(memory):
    memory.save("独一无二的内容")
    assert memory.exists_by_content("独一无二的内容") is True
    assert memory.exists_by_content("不存在的内容") is False


def test_count_with_session_and_invalid_filter(memory):
    m1 = memory.save("甲", session_id="s1")
    memory.save("乙", session_id="s2")
    memory.invalidate(m1)
    assert memory.count() == 1
    assert memory.count(session_id="s2") == 1
    assert memory.count(session_id="s1") == 0


# ---------------------------------------------------------------------------
# delete / invalidate
# ---------------------------------------------------------------------------


def test_delete_removes_from_store_and_search(memory):
    mid = memory.save("用户喜欢火锅")
    assert memory.delete(mid) is True
    assert memory.get_by_id(mid) is None
    # FTS 行同步删除；FTS 空命中回退 LIKE 也不应捞回已删行
    assert memory.search("火锅") == []
    assert memory.delete(mid) is False


def test_invalidate_excludes_from_search_but_keeps_row(memory):
    mid = memory.save("用户喜欢火锅")
    assert memory.invalidate(mid) is True
    # P3：检索路径（FTS + LIKE + count）全部排除失效行
    assert memory.search("火锅") == []
    assert memory.count() == 0
    # 审计语义：get_by_id 仍可取回原行
    assert memory.get_by_id(mid)["content"] == "用户喜欢火锅"
    assert memory.get_by_id(mid)["invalid_at"] is not None
    # 幂等：重复 invalidate 返回 False
    assert memory.invalidate(mid) is False


# ---------------------------------------------------------------------------
# update_tags
# ---------------------------------------------------------------------------


def test_update_tags_roundtrip_and_fts_sync(memory):
    mid = memory.save("用户喜欢火锅")
    assert memory.update_tags(mid, ["饮食", "新标签"]) is True
    got = memory.get_by_id(mid)
    assert got["tags"] == ["饮食", "新标签"]
    # FTS 行已按新 tags 重建：按标签检索命中
    hits = memory.search("火锅", tags=["新标签"])
    assert len(hits) == 1
    assert memory.update_tags("no-such-id", ["x"]) is False


# ---------------------------------------------------------------------------
# scope 轴
# ---------------------------------------------------------------------------


def test_save_default_scope_is_user(memory):
    got = memory.get_by_id(memory.save("默认作用域"))
    assert got["scope"] == "user"
    assert got["project_key"] is None


def test_search_by_scope_across_sessions(memory):
    memory.save("甲会话用户记忆", session_id="s1")
    memory.save("乙会话用户记忆", session_id="s2")
    hits = memory.search("用户记忆", scope="user")
    assert len(hits) == 2  # 跨会话按作用域轴检索


def test_search_project_scope_without_key_short_circuits(memory):
    memory.save("某条记忆")
    # 非法组合（project 无 key）直接返回空，不抛错
    assert memory.search("记忆", scope="project") == []
