"""P1 记忆作用域轴 (scope × project_key) 回归测试。

覆盖:
- scope 模块: 绑定解析 / 写入判定 / 可见性过滤
- episodic / semantic 存储层: 自动判定落库、显式声明、降级
- 作用域轴跨会话检索 (scope='project'/'user')
- MemoryManager.search_memories 的 scope 路由
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory import scope as memory_scope
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit

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
def episodic(db: Database) -> EpisodicMemory:
    return EpisodicMemory(db)


@pytest.fixture()
def semantic(db: Database) -> SemanticMemory:
    return SemanticMemory(db)


@pytest.fixture()
def manager(db: Database) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


# ---------- scope 模块 ----------


def test_schema_has_scope_columns(db: Database) -> None:
    conn = db.get_connection()
    for table in ("memories_episodic", "memories_semantic"):
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert {"scope", "project_key"} <= cols, table


def test_resolve_project_key_bound_and_unbound(db: Database) -> None:
    ensure_session(db, "s1")
    _bind(db, "s1", PROJ_A)
    assert memory_scope.resolve_session_project_key(db, "s1") == PROJ_A
    assert memory_scope.resolve_session_project_key(db, "s2") is None
    assert memory_scope.resolve_session_project_key(db, None) is None
    assert memory_scope.resolve_session_project_key(db, "default") is None


def test_finalize_scope_downgrade_without_binding(db: Database) -> None:
    scope, key = memory_scope.finalize_scope(db, "project", None, None)
    assert (scope, key) == ("user", None)


def test_finalize_scope_non_project_clears_key(db: Database) -> None:
    scope, key = memory_scope.finalize_scope(db, "user", PROJ_A, None)
    assert (scope, key) == ("user", None)


def test_is_row_visible_rules() -> None:
    project_row = {"scope": "project", "project_key": PROJ_A}
    user_row = {"scope": "user", "project_key": None}
    legacy_row = {"scope": None, "project_key": None}
    assert memory_scope.is_row_visible(project_row, PROJ_A)
    assert not memory_scope.is_row_visible(project_row, PROJ_B)
    assert not memory_scope.is_row_visible(project_row, None)
    assert memory_scope.is_row_visible(user_row, None)
    assert memory_scope.is_row_visible(legacy_row, PROJ_B)


# ---------- 写入路径自动判定 ----------


def test_episodic_save_derives_project_scope(db: Database, episodic: EpisodicMemory) -> None:
    ensure_session(db, "s1")
    _bind(db, "s1", PROJ_A)
    mid = episodic.save("项目用 FastAPI", session_id="s1")
    row = episodic.get_by_id(mid)
    assert row["scope"] == "project"
    assert row["project_key"] == PROJ_A


def test_episodic_save_unbound_falls_back_to_user(
    db: Database, episodic: EpisodicMemory
) -> None:
    ensure_session(db, "s1")
    mid = episodic.save("用户喜欢简洁回答", session_id="s1")
    row = episodic.get_by_id(mid)
    assert row["scope"] == "user"
    assert row["project_key"] is None


def test_episodic_save_explicit_scope_override(
    db: Database, episodic: EpisodicMemory
) -> None:
    ensure_session(db, "s1")
    _bind(db, "s1", PROJ_A)
    mid = episodic.save("全局常识", session_id="s1", scope="global")
    row = episodic.get_by_id(mid)
    assert row["scope"] == "global"
    assert row["project_key"] is None


def test_semantic_save_derives_project_scope(semantic: SemanticMemory) -> None:
    mid = semantic.save("该仓库记忆层用 SQLite", session_id=None, scope="project",
                        project_key=PROJ_A)
    row = semantic.get_by_id(mid)
    assert row["scope"] == "project"
    assert row["project_key"] == PROJ_A


# ---------- 作用域轴跨会话检索 ----------


def test_episodic_scope_project_search_cross_session(
    db: Database, episodic: EpisodicMemory
) -> None:
    ensure_session(db, "s1")
    ensure_session(db, "s2")
    ensure_session(db, "s3")
    _bind(db, "s1", PROJ_A)
    _bind(db, "s2", PROJ_A)
    _bind(db, "s3", PROJ_B)
    episodic.save("部署脚本在 scripts/deploy", session_id="s1")
    episodic.save("别的项目的秘密配置", session_id="s3")

    # 同项目另一会话 (s2) 的 s1 记忆可被跨会话检索到
    results = episodic.search("deploy", scope="project", project_key=PROJ_A)
    assert any("deploy" in r["content"] for r in results)
    # 其他项目的 project 记忆不可见
    results_b = episodic.search("deploy", scope="project", project_key=PROJ_B)
    assert results_b == []


def test_episodic_scope_project_without_key_returns_empty(
    episodic: EpisodicMemory,
) -> None:
    assert episodic.search("anything", scope="project") == []


def test_episodic_scope_user_search_excludes_project_rows(
    db: Database, episodic: EpisodicMemory
) -> None:
    ensure_session(db, "s1")
    _bind(db, "s1", PROJ_A)
    episodic.save("shared note about widgets", session_id="s1", scope="user")
    episodic.save("project only note about widgets", session_id="s1")

    results = episodic.search("widgets", scope="user")
    assert all(r["scope"] == "user" for r in results)
    assert any("shared" in r["content"] for r in results)


def test_semantic_scope_search_across_sessions(
    db: Database, semantic: SemanticMemory
) -> None:
    mid = semantic.save("API gateway uses Kong", session_id="sx", scope="project",
                        project_key=PROJ_A)
    assert mid
    results = semantic.search("Kong", scope="project", project_key=PROJ_A)
    assert any(r["id"] == mid for r in results)
    assert semantic.search("Kong", scope="project", project_key=PROJ_B) == []


# ---------- MemoryManager 编排 ----------


def test_manager_memorize_stamps_project_scope(
    db: Database, manager: MemoryManager
) -> None:
    ensure_session(db, "s1")
    _bind(db, "s1", PROJ_A)
    mid = manager.memorize("构建命令是 make build", memory_type="episodic",
                           session_id="s1")
    row = manager.episodic.get_by_id(mid)
    assert row["scope"] == "project"
    assert row["project_key"] == PROJ_A


def test_manager_search_memories_scope_routing(
    db: Database, manager: MemoryManager
) -> None:
    ensure_session(db, "s1")
    ensure_session(db, "s2")
    _bind(db, "s1", PROJ_A)
    _bind(db, "s2", PROJ_A)
    manager.memorize("数据库迁移用 alembic", memory_type="episodic", session_id="s1")

    # 另一会话按 session 检索不到 (旧隔离语义不变)
    assert manager.search_memories("alembic", "episodic", 5, session_id="s2") == []
    # 但同项目按作用域轴可检索到
    hits = manager.search_memories("alembic", "episodic", 5, session_id="s2",
                                   scope="project")
    assert any("alembic" in h["content"] for h in hits)


def test_manager_search_project_for_unbound_session(
    db: Database, manager: MemoryManager
) -> None:
    ensure_session(db, "s1")
    _bind(db, "s1", PROJ_A)
    manager.memorize("项目内有用的事实", memory_type="episodic", session_id="s1")
    # 未绑定会话没有项目归属 → 空结果而非泄漏
    assert manager.search_memories("有用的事实", None, 5, session_id=None,
                                   scope="project") == []
