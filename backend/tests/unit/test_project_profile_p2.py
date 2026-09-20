"""P2 项目画像 (项目级 MEMORY.md) 回归测试。

覆盖:
- project_profile 表 schema
- ProjectProfileStore: 分组快照 / 冻结语义 / 去重 / 限长 / 删除
- MemoryManager.get_context 的项目画像注入（绑定 / 未绑定 / 跨项目隔离）
- MemoryContext.format 的【用户画像】/【项目画像】分段
- 写入台账 project_profile kind + undo 路由
- /memory/project-profile CRUD 端点
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.domain.memory import MemoryContext
from backend.memory import scope as memory_scope
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.project_profile import (
    ProjectProfileStore,
    get_project_profile,
)
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.memory.write_ledger import (
    KIND_PROJECT_PROFILE,
    get_write_ledger,
)
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit

BASE = "/api/v1/memory"
PROJ_A = "/tmp/proj-a"
PROJ_B = "/tmp/proj-b"


def _bind(db: Database, session_id: str, workspace_path: str) -> None:
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO session_workspace_bindings "
        "(session_id, workspace_path, generation, activated_at, revoked_at) "
        "VALUES (?, ?, 1, 1, NULL)",
        (session_id, workspace_path),
    )
    conn.commit()


@pytest.fixture()
def db(tmp_db_path: str) -> Database:
    d = Database(db_path=tmp_db_path)
    d.init_db()
    return d


@pytest.fixture()
def store(db: Database) -> ProjectProfileStore:
    s = ProjectProfileStore(db)
    s.load()
    return s


@pytest.fixture()
def manager(db: Database) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


# ---------- schema / store ----------


def test_schema_has_project_profile_table(db: Database) -> None:
    conn = db.get_connection()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(project_profile)")}
    assert {
        "id",
        "project_key",
        "content",
        "category",
        "importance",
        "source",
        "created_at",
    } <= cols


def test_add_list_snapshot(store: ProjectProfileStore) -> None:
    pid = store.add(PROJ_A, "接口统一用 REST", category="convention", importance=8)
    assert pid
    assert store.get_snapshot(PROJ_A) == (
        f"## PROJECT PROFILE ({PROJ_A})\n- 接口统一用 REST"
    )
    items = store.list(PROJ_A)
    assert len(items) == 1
    assert items[0]["id"] == pid
    # 其他项目互不可见
    assert store.get_snapshot(PROJ_B) == ""
    assert store.list(PROJ_B) == []


def test_empty_project_key_rejected(store: ProjectProfileStore) -> None:
    assert store.add("", "无归属内容") is None
    assert store.get_snapshot("") == ""
    assert store.get_snapshot(None) == ""
    assert store.get_core_items(None) == []


def test_dedupe_within_project(store: ProjectProfileStore) -> None:
    store.add(PROJ_A, "接口统一用 REST")
    assert store.add(PROJ_A, "接口统一用 REST") is None  # 完全一致
    assert store.add(PROJ_A, "统一用 REST") is None  # 子串包含
    # 跨项目不去重
    assert store.add(PROJ_B, "接口统一用 REST")


def test_char_limit_truncates_by_importance(db: Database) -> None:
    store = ProjectProfileStore(db, char_limit=40)
    store.add(PROJ_A, "高" * 30, importance=9)
    store.add(PROJ_A, "低" * 30, importance=1)
    snapshot = store.get_snapshot(PROJ_A)
    assert "高" * 30 in snapshot
    assert "低" * 30 not in snapshot


def test_frozen_snapshot_semantics(store: ProjectProfileStore) -> None:
    store.add(PROJ_A, "第一条")
    frozen = store.get_snapshot(PROJ_A)
    store.add(PROJ_A, "第二条写入不应改快照", importance=10)
    assert store.get_snapshot(PROJ_A) == frozen  # add 不刷新（prefix cache）
    store.invalidate(PROJ_A)
    assert "第二条写入不应改快照" in store.get_snapshot(PROJ_A)  # 显式刷新
    assert "- 第一条" in store.get_snapshot(PROJ_A)


def test_get_core_items_carries_scope(store: ProjectProfileStore) -> None:
    store.add(PROJ_A, "约定条目")
    items = store.get_core_items(PROJ_A)
    assert items[0]["scope"] == "project"
    assert items[0]["project_key"] == PROJ_A


def test_delete_rebuilds_snapshot(store: ProjectProfileStore) -> None:
    pid = store.add(PROJ_A, "会被删除")
    assert store.delete(pid) is True
    assert store.delete(pid) is False
    assert store.get_snapshot(PROJ_A) == ""


# ---------- manager.get_context 注入 ----------


def test_get_context_injects_project_profile_for_bound_session(
    db: Database, manager: MemoryManager
) -> None:
    ensure_session(db, "s1")
    _bind(db, "s1", PROJ_A)
    # get_context 走全局单例（conftest 已重置到临时库）；
    # add 不改快照，手动 invalidate 模拟"新会话启动前刷新"
    singleton = get_project_profile()
    singleton.add(PROJ_A, "该项目用 pnpm 而非 npm", importance=9)
    singleton.invalidate(PROJ_A)
    ctx = manager.get_context(session_id="s1")
    assert "PROJECT PROFILE" in ctx
    assert "pnpm" in ctx


def test_get_context_no_profile_for_unbound_or_foreign_session(
    db: Database, manager: MemoryManager
) -> None:
    singleton = get_project_profile()
    singleton.add(PROJ_A, "项目私有约定", importance=9)
    singleton.invalidate(PROJ_A)
    # 未绑定会话
    ensure_session(db, "s-out")
    ctx = manager.get_context(session_id="s-out")
    assert "PROJECT PROFILE" not in ctx
    # 绑定到"别的项目"的会话也看不到 PROJ_A 画像
    ensure_session(db, "s-b")
    _bind(db, "s-b", PROJ_B)
    ctx_b = manager.get_context(session_id="s-b")
    assert "项目私有约定" not in ctx_b


# ---------- MemoryContext.format 分段 ----------


def test_format_splits_user_and_project_labels() -> None:
    ctx = MemoryContext(
        core=[
            {"content": "用户偏好简洁", "importance": 8},
            {
                "content": "项目用 pnpm",
                "importance": 8,
                "scope": "project",
                "project_key": PROJ_A,
            },
        ]
    )
    text = ctx.format()
    assert "【用户画像】" in text
    assert "【项目画像】" in text
    user_block, project_block = text.split("【项目画像】")
    assert "用户偏好简洁" in user_block
    assert "项目用 pnpm" in project_block


# ---------- 台账 kind / undo 路由 ----------


class TestProjectProfileRoutes:
    @pytest.mark.asyncio()
    async def test_create_with_explicit_key(self, client):
        r = await client.post(
            f"{BASE}/project-profile",
            json={"content": "接口统一用 REST", "project_key": PROJ_A},
        )
        assert r.status_code == 200
        assert r.json()["item"]["project_key"] == PROJ_A

    @pytest.mark.asyncio()
    async def test_create_resolves_from_bound_session(self, client, db):
        ensure_session(db, "s1")
        _bind(db, "s1", PROJ_A)
        r = await client.post(
            f"{BASE}/project-profile",
            json={"content": "从会话解析归属", "session_id": "s1"},
        )
        assert r.status_code == 200
        assert r.json()["project_key"] == PROJ_A

    @pytest.mark.asyncio()
    async def test_create_without_attribution_is_400(self, client):
        r = await client.post(
            f"{BASE}/project-profile",
            json={"content": "无处安放"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio()
    async def test_list_by_session(self, client, db):
        ensure_session(db, "s1")
        _bind(db, "s1", PROJ_A)
        get_project_profile().add(PROJ_A, "列表可见条目")
        r = await client.get(f"{BASE}/project-profile", params={"session_id": "s1"})
        body = r.json()
        assert body["project_key"] == PROJ_A
        assert any(i["content"] == "列表可见条目" for i in body["items"])
        # 未绑定会话 → 空
        r2 = await client.get(f"{BASE}/project-profile", params={"session_id": "nope"})
        assert r2.json()["items"] == []
        assert r2.json()["snapshot"] == ""

    @pytest.mark.asyncio()
    async def test_undo_routes_to_project_profile(self, client):
        pid = get_project_profile().add(PROJ_A, "可撤销的条目")
        get_write_ledger().record(
            memory_id=pid,
            kind=KIND_PROJECT_PROFILE,
            content="可撤销的条目",
            session_id="s-undo",
            category="convention",
            memory_type="profile",
        )
        r = await client.post(
            f"{BASE}/undo-write", json={"session_id": "s-undo", "id": pid}
        )
        assert r.status_code == 200
        assert r.json()["kind"] == "project_profile"
        assert get_project_profile().list(PROJ_A) == []
        # 再撤一次 → 404
        r2 = await client.post(
            f"{BASE}/undo-write",
            json={"session_id": "s-undo", "id": pid},
        )
        assert r2.status_code == 404

    @pytest.mark.asyncio()
    async def test_delete_endpoint(self, client):
        pid = get_project_profile().add(PROJ_A, "将被删除")
        r = await client.delete(f"{BASE}/project-profile/{pid}")
        assert r.status_code == 200
        assert get_project_profile().list(PROJ_A) == []


def test_scope_module_unchanged_public_surface() -> None:
    # P2 不应破坏 P1 公共 API
    assert set(memory_scope.VALID_SCOPES) == {"user", "project", "global"}
