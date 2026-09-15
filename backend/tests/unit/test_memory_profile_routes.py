"""对标 S2：记忆写入台账 / 撤销 / 用户画像 CRUD 端点测试。"""

import pytest

from backend.data.session_repo import SessionRepository
from backend.memory import get_memory_manager
from backend.memory.user_profile import get_user_profile
from backend.memory.write_ledger import KIND_MEMORY, KIND_PROFILE, get_write_ledger

pytestmark = pytest.mark.unit

BASE = "/api/v1/memory"


class TestRecentWrites:
    @pytest.mark.asyncio
    async def test_empty(self, client):
        r = await client.get(f"{BASE}/recent-writes", params={"session_id": "s-none"})
        assert r.status_code == 200
        assert r.json() == {"items": [], "latest_seq": 0}

    @pytest.mark.asyncio
    async def test_cursor(self, client):
        ledger = get_write_ledger()
        a = ledger.record(memory_id="m1", kind=KIND_MEMORY, content="喜欢火锅", session_id="s1")
        b = ledger.record(memory_id="p1", kind=KIND_PROFILE, content="偏好简洁", session_id="s1")
        r = await client.get(f"{BASE}/recent-writes", params={"session_id": "s1"})
        body = r.json()
        assert [i["id"] for i in body["items"]] == ["m1", "p1"]
        assert body["latest_seq"] == b.seq
        r2 = await client.get(
            f"{BASE}/recent-writes", params={"session_id": "s1", "after_seq": a.seq}
        )
        assert [i["id"] for i in r2.json()["items"]] == ["p1"]
        assert r2.json()["items"][0]["kind"] == "profile"


class TestUndoWrite:
    @pytest.mark.asyncio
    async def test_undo_memory(self, client):
        sid = SessionRepository().create(title="撤销测试").id
        mm = get_memory_manager()
        mid = mm.memorize("用户喜欢火锅", "episodic", 5, [], session_id=sid)
        get_write_ledger().record(memory_id=mid, kind=KIND_MEMORY, content="x", session_id=sid)
        r = await client.post(f"{BASE}/undo-write", json={"session_id": sid, "id": mid})
        assert r.status_code == 200
        assert r.json()["kind"] == "memory"
        assert get_write_ledger().find(sid, mid) is None
        # 情景记忆为软删除（is_valid=0），已不在 recent 列表中
        assert all(m["id"] != mid for m in mm.episodic.get_recent(limit=20, session_id=sid))

    @pytest.mark.asyncio
    async def test_undo_unknown_id(self, client):
        r = await client.post(f"{BASE}/undo-write", json={"session_id": "s1", "id": "nope"})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_undo_profile(self, client):
        store = get_user_profile()
        pid = store.add("用户偏好简洁回答", category="preference", importance=7)
        get_write_ledger().record(memory_id=pid, kind=KIND_PROFILE, content="x", session_id="s1")
        r = await client.post(f"{BASE}/undo-write", json={"session_id": "s1", "id": pid})
        assert r.status_code == 200
        assert r.json()["kind"] == "profile"
        assert all(e["id"] != pid for e in store.list())

    @pytest.mark.asyncio
    async def test_undo_profile_without_ledger_falls_back(self, client):
        store = get_user_profile()
        pid = store.add("用户是后端工程师", category="identity", importance=6)
        r = await client.post(f"{BASE}/undo-write", json={"session_id": "s-other", "id": pid})
        assert r.status_code == 200
        assert all(e["id"] != pid for e in store.list())


class TestProfileCrud:
    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        r = await client.get(f"{BASE}/profile")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert "preference" in body["categories"]
        assert body["char_limit"] > 0

    @pytest.mark.asyncio
    async def test_create_update_delete(self, client):
        r = await client.post(
            f"{BASE}/profile",
            json={"content": "用户偏好用 GB/T 7714 引用格式", "category": "preference", "importance": 8},
        )
        assert r.status_code == 200
        item = r.json()["item"]
        assert item["category"] == "preference"
        # 立即生效：快照包含新内容
        assert "GB/T 7714" in get_user_profile().get_snapshot()

        # 重复 → 409
        r_dup = await client.post(
            f"{BASE}/profile", json={"content": "用户偏好用 GB/T 7714 引用格式"}
        )
        assert r_dup.status_code == 409

        # 更新
        r_up = await client.put(
            f"{BASE}/profile/{item['id']}",
            json={"content": "用户偏好 APA 引用格式", "importance": 9},
        )
        assert r_up.status_code == 200
        new_item = r_up.json()["item"]
        assert new_item["content"] == "用户偏好 APA 引用格式"
        assert new_item["importance"] == 9
        assert new_item["category"] == "preference"
        listing = (await client.get(f"{BASE}/profile")).json()["items"]
        assert len(listing) == 1

        # 删除
        r_del = await client.delete(f"{BASE}/profile/{new_item['id']}")
        assert r_del.status_code == 200
        assert (await client.get(f"{BASE}/profile")).json()["items"] == []
        r_del2 = await client.delete(f"{BASE}/profile/{new_item['id']}")
        assert r_del2.status_code == 404

    @pytest.mark.asyncio
    async def test_update_missing(self, client):
        r = await client.put(f"{BASE}/profile/nope", json={"content": "x"})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_update_empty_content(self, client):
        r = await client.post(f"{BASE}/profile", json={"content": "用户喜欢深色主题"})
        pid = r.json()["item"]["id"]
        r2 = await client.put(f"{BASE}/profile/{pid}", json={"content": "   "})
        assert r2.status_code == 400
        # 原条目仍在
        assert any(e["id"] == pid for e in get_user_profile().list())
