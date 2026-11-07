"""P0-2：学到的偏好真正注入 user_profile（进 system prompt 冻结快照）。

覆盖：
* ``PreferenceLearningTask`` 跑完后 user_profile 出现 preference 类条目
* 进化任务写 user_profile **不触发** ``invalidate()``（hermes 冻结快照语义）
* ``GET /memory/preferences/learned`` 列出已学偏好
* ``PUT /memory/preferences/learned`` 同时更新 preferences 表与 user_profile
* ``POST /memory/profile/refresh`` 显式重建冻结快照，新条目立即可读
"""

from __future__ import annotations

import time

import pytest

from backend.api import legacy_memory_routes as legacy_routes
from backend.data.database import Database
from backend.memory.user_profile import UserProfileStore
from backend.scheduler.evolution import PreferenceLearningTask


@pytest.fixture()
def tmp_db():
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


def _insert_user_message(db, content: str) -> None:
    conn = db.get_connection()
    session_id = "sess-pref-inject"
    now = int(time.time())
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", now, now),
    )
    conn.execute(
        """INSERT INTO messages (id, session_id, role, content, created_at)
           VALUES (?, ?, 'user', ?, ?)""",
        (f"msg-{abs(hash(content))}", session_id, content, now),
    )
    conn.commit()


# ---------- 进化任务写 user_profile ----------


def test_preference_learning_writes_user_profile(tmp_db):
    """偏好学完后 user_profile 里出现 preference 类条目。"""
    _insert_user_message(tmp_db, "回答太短了，请详细一点")
    task = PreferenceLearningTask(db=tmp_db, llm_client=None, config={})

    learned = task.run()

    assert learned > 0
    rows = tmp_db.get_connection().execute(
        "SELECT content, category, importance FROM user_profile"
    ).fetchall()
    assert len(rows) >= 1
    assert all(r["category"] == "preference" for r in rows)
    # 内容里应含偏好维度名
    assert any("response_length" in r["content"] for r in rows)


def test_preference_learning_does_not_invalidate_snapshot(tmp_db, monkeypatch):
    """hermes 语义：写 user_profile 不刷新冻结快照（保 prefix cache）。

    进化任务自己 new 一个 UserProfileStore，测试通过 patch
    ``UserProfileStore.invalidate`` 记录调用次数来断言它没被调。
    """
    calls = []
    original_invalidate = UserProfileStore.invalidate

    def _tracking_invalidate(self):
        calls.append(1)
        return original_invalidate(self)

    monkeypatch.setattr(UserProfileStore, "invalidate", _tracking_invalidate)

    _insert_user_message(tmp_db, "语气太严肃了，友好一点")
    task = PreferenceLearningTask(db=tmp_db, llm_client=None, config={})
    task.run()

    assert calls == [], "偏好学习不应触发 invalidate()（会破坏 prefix cache）"


def test_preference_learning_still_writes_preferences_table(tmp_db):
    """preferences 表的 pref_* 键是既有行为，不能因本轮改造而丢失。"""
    _insert_user_message(tmp_db, "回答太短了，请详细一点")
    task = PreferenceLearningTask(db=tmp_db, llm_client=None, config={})
    task.run()

    rows = tmp_db.get_connection().execute(
        "SELECT key FROM preferences WHERE key LIKE 'pref_%'"
    ).fetchall()
    assert len(rows) >= 1


# ---------- 路由：GET /memory/preferences/learned ----------


def test_list_learned_preferences_route(tmp_db, monkeypatch):
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)
    tmp_db.get_connection().execute(
        "INSERT INTO preferences (key, value, value_type, category, created_at, updated_at) "
        "VALUES ('pref_response_length', 'long', 'string', 'preference', 1, 2)"
    )
    tmp_db.get_connection().commit()

    result = legacy_routes.list_learned_preferences()

    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["key"] == "pref_response_length"
    assert item["value"] == "long"


def test_list_learned_preferences_ignores_non_pref_keys(tmp_db, monkeypatch):
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)
    conn = tmp_db.get_connection()
    conn.execute(
        "INSERT INTO preferences (key, value, value_type, category, created_at, updated_at) "
        "VALUES ('other_key', 'x', 'string', 'misc', 1, 2)"
    )
    conn.commit()

    result = legacy_routes.list_learned_preferences()

    assert result["items"] == []


# ---------- 路由：PUT /memory/preferences/learned ----------


def test_update_learned_preference_updates_both_stores(tmp_db, monkeypatch):
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)
    store = UserProfileStore(tmp_db)
    store.load()
    monkeypatch.setattr("backend.memory.user_profile.get_user_profile", lambda: store)

    result = legacy_routes.update_learned_preference(
        legacy_routes.LearnedPreferenceUpdate(key="pref_tone", value="professional")
    )

    assert result["status"] == "ok"
    # preferences 表
    row = tmp_db.get_connection().execute(
        "SELECT value FROM preferences WHERE key='pref_tone'"
    ).fetchone()
    assert row["value"] == "professional"
    # user_profile
    profile_rows = tmp_db.get_connection().execute(
        "SELECT content, category FROM user_profile"
    ).fetchall()
    assert len(profile_rows) == 1
    assert "professional" in profile_rows[0]["content"]
    assert profile_rows[0]["category"] == "preference"


def test_update_learned_preference_rejects_non_pref_key(tmp_db, monkeypatch):
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)

    with pytest.raises(legacy_routes.HTTPException) as exc:
        legacy_routes.update_learned_preference(
            legacy_routes.LearnedPreferenceUpdate(key="other", value="x")
        )

    assert exc.value.status_code == 422


def test_update_learned_preference_rejects_empty_value(tmp_db, monkeypatch):
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)

    with pytest.raises(legacy_routes.HTTPException) as exc:
        legacy_routes.update_learned_preference(
            legacy_routes.LearnedPreferenceUpdate(key="pref_tone", value="  ")
        )

    assert exc.value.status_code == 422


def test_update_learned_preference_replaces_old_user_profile_entry(tmp_db, monkeypatch):
    """反复纠正同一偏好时，user_profile 不应堆积相互冲突的旧条目。

    用户把 ``pref_tone`` 从 ``professional`` 改成 ``casual``，
    user_profile 应该只剩 ``casual`` 这一条，而不是同时存在两条。
    """
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)
    store = UserProfileStore(tmp_db)
    store.load()
    monkeypatch.setattr("backend.memory.user_profile.get_user_profile", lambda: store)

    legacy_routes.update_learned_preference(
        legacy_routes.LearnedPreferenceUpdate(key="pref_tone", value="professional")
    )
    legacy_routes.update_learned_preference(
        legacy_routes.LearnedPreferenceUpdate(key="pref_tone", value="casual")
    )

    profile_rows = tmp_db.get_connection().execute(
        "SELECT content FROM user_profile WHERE content LIKE '用户偏好 tone:%'"
    ).fetchall()
    contents = [r["content"] for r in profile_rows]
    # 只有最新的那条，旧的被替换
    assert len(contents) == 1
    assert contents[0] == "用户偏好 tone: casual"


# ---------- 路由：POST /memory/profile/refresh ----------


def test_refresh_user_profile_route_rebuilds_snapshot(tmp_db, monkeypatch):
    """刷新后快照能读到此前写入但未进快照的条目。"""
    store = UserProfileStore(tmp_db)
    store.load()
    monkeypatch.setattr("backend.memory.user_profile.get_user_profile", lambda: store)

    # 直接写 DB，绕过 add()（模拟进化任务写后未刷新快照的既有状态）
    conn = tmp_db.get_connection()
    conn.execute(
        "INSERT INTO user_profile (id, content, category, importance, created_at, updated_at) "
        "VALUES ('p1', '用户偏好 response_length: long', 'preference', 6, 1, 1)"
    )
    conn.commit()

    # 刷新前：快照里没有
    assert "response_length" not in store.get_snapshot()

    result = legacy_routes.refresh_user_profile()

    assert result["status"] == "ok"
    assert result["items_count"] >= 1
    assert "response_length" in store.get_snapshot()
