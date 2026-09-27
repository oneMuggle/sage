"""R165 — ConventionManager 惯例管理单元测试。

覆盖：add/get 往返（is_active bool 还原）、update 白名单、delete、
get_active 过滤排序、get_context_prompt 行格式、decay 衰减与停用、
promote/demote 置信度边界、get_stats、无 llm_client 学习回退。
DB 用真实内存 SQLite。
"""

from __future__ import annotations

import time

import pytest

from backend.core.conventions import Convention, ConventionManager
from backend.data.database import Database

pytestmark = pytest.mark.unit


def _convention(**overrides):
    base = dict(
        id="c1",
        name="先读后写",
        description="修改文件前先读取目标文件",
        category="tool_usage",
        confidence=0.8,
    )
    base.update(overrides)
    return Convention(**base)


@pytest.fixture()
def manager():
    db = Database(db_path=":memory:")
    db.init_db()
    return ConventionManager(llm_client=None)


# ---------------------------------------------------------------------------
# add / get / update / delete
# ---------------------------------------------------------------------------


def test_add_and_get_roundtrip(manager):
    manager.add(_convention())
    got = manager.get("c1")
    assert got is not None
    assert got.name == "先读后写"
    assert got.category == "tool_usage"
    assert got.confidence == 0.8
    assert got.is_active is True  # int 1 还原为 bool
    assert isinstance(got.is_active, bool)


def test_get_missing_returns_none(manager):
    assert manager.get("ghost") is None


def test_update_whitelisted_fields(manager):
    manager.add(_convention())
    ok = manager.update("c1", description="新描述", confidence=0.9)
    assert ok is True
    got = manager.get("c1")
    assert got.description == "新描述"
    assert got.confidence == 0.9


def test_update_ignores_non_whitelisted_keys(manager):
    manager.add(_convention())
    ok = manager.update("c1", category="hacked", ghost_key=1)
    assert ok is False  # 无有效键 → False，DB 未动


def test_update_unknown_id_returns_false(manager):
    assert manager.update("ghost", confidence=0.1) is False


def test_delete_hit_and_miss(manager):
    manager.add(_convention())
    assert manager.delete("c1") is True
    assert manager.delete("c1") is False
    assert manager.get("c1") is None


# ---------------------------------------------------------------------------
# get_active / 上下文注入
# ---------------------------------------------------------------------------


def test_get_active_filters_and_sorts_by_confidence(manager):
    manager.add(_convention(id="high", confidence=0.9, category="coding"))
    manager.add(_convention(id="low-active", confidence=0.6, category="coding"))
    manager.add(_convention(id="inactive", confidence=0.95, is_active=False))

    active = manager.get_active(category="coding")
    assert [c.id for c in active] == ["high", "low-active"]  # 置信度降序
    assert manager.get_active()  # 无过滤也有结果


def test_get_context_prompt_empty_when_no_active(manager):
    assert manager.get_context_prompt() == ""


def test_get_context_prompt_line_format(manager):
    manager.add(_convention(category="tool_usage"))
    prompt = manager.get_context_prompt()
    assert prompt.startswith("\n用户惯例:")
    assert "- [TOOL_USAGE] 先读后写: 修改文件前先读取目标文件" in prompt


# ---------------------------------------------------------------------------
# decay / promote / demote
# ---------------------------------------------------------------------------


def _seed_aged(manager, age_days=40, confidence=0.8):
    old = int(time.time()) - age_days * 86400
    conv = _convention(id="aged", confidence=confidence)
    manager.add(conv)
    conn = manager.db.get_connection()
    conn.execute(
        "UPDATE conventions SET last_updated = ? WHERE id = ?", (old, "aged")
    )
    conn.commit()


def test_decay_reduces_confidence_of_stale_conventions(manager):
    _seed_aged(manager, confidence=0.8)
    manager.decay(days=30)
    got = manager.get("aged")
    assert got.confidence == pytest.approx(0.8 * 0.9)


def test_decay_disables_below_min_confidence(manager):
    # 衰减 WHERE 要求 confidence > MIN_CONFIDENCE(0.1) 才触发；
    # 0.11 * 0.9 = 0.099 < 0.1 → 衰减后被二次 UPDATE 停用
    _seed_aged(manager, confidence=0.11)
    manager.decay(days=30)
    got = manager.get("aged")
    assert got.confidence == pytest.approx(0.099)
    assert got.is_active is False


def test_decay_skips_recently_updated(manager):
    conv = _convention(id="fresh", confidence=0.8)
    manager.add(conv)
    manager.decay(days=30)
    assert manager.get("fresh").confidence == 0.8  # 未超期不衰减


def test_promote_and_demote_bounds(manager):
    manager.add(_convention(id="mid", confidence=0.5))
    manager.promote("mid")
    assert manager.get("mid").confidence == pytest.approx(0.65)
    manager.demote("mid")
    manager.demote("mid")
    manager.demote("mid")
    assert manager.get("mid").confidence == pytest.approx(0.05)
    manager.demote("mid")
    assert manager.get("mid").confidence == 0.0  # 下限 0


def test_promote_unknown_id_false(manager):
    assert manager.promote("ghost") is False
    assert manager.demote("ghost") is False


# ---------------------------------------------------------------------------
# 统计与学习回退
# ---------------------------------------------------------------------------


def test_get_stats_totals_and_by_category(manager):
    manager.add(_convention(id="a", category="coding"))
    manager.add(_convention(id="b", category="coding", is_active=False))
    manager.add(_convention(id="c", category="memory"))
    stats = manager.get_stats()
    assert stats["total"] == 3
    assert stats["active"] == 2
    assert stats["by_category"] == {"coding": 2, "memory": 1}


@pytest.mark.asyncio()
async def test_learn_without_llm_returns_empty(manager):
    assert await manager.learn_from_conversation([{"role": "user", "content": "x"}]) == []


def test_convention_to_dict_nine_keys():
    d = _convention().to_dict()
    assert set(d) == {
        "id", "name", "description", "category", "confidence",
        "usage_count", "created_at", "last_updated", "is_active",
    }
