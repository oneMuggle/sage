"""M3-Task 7 — 提升为共享（promote）与专家删除级联清理（purge）测试。

契约：
- 提升把私有行 ``agent_id`` 置 NULL（共享层），并写一条
  ``memories_evolution_log`` 审计行（``operation = promote``）；
- 审计写失败 → 整个提升回滚（归属不变），绝不"改了但没记录"；
- 已是共享层的行 → 幂等返回 ``already_shared``，不写审计行；
- 级联清理只删该专家的私有行，共享层与其它专家的行不动；
- 向量条目按 ``memories_vec%`` 全表清扫（含非默认嵌入维度表）。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

from backend.api import legacy_memory_routes as memory_routes
from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory

pytestmark = pytest.mark.unit

AGENT_WRITER = "specialist-writer"
AGENT_CODER = "specialist-coder"


@pytest.fixture()
def db(tmp_db_path: str) -> Database:
    d = Database(db_path=tmp_db_path)
    d.init_db()
    return d


@pytest.fixture()
def manager(db: Database) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


def _agent_of(db: Database, table: str, memory_id: str):
    row = db.get_connection().execute(
        f"SELECT agent_id FROM {table} WHERE id = ?", (memory_id,)
    ).fetchone()
    return None if row is None else row["agent_id"]


def _evolution_rows(db: Database):
    return db.get_connection().execute(
        "SELECT memory_type, memory_id, operation, reason, created_at "
        "FROM memories_evolution_log ORDER BY created_at"
    ).fetchall()


# ---------- promote：归属变更 ----------


def test_promote_episodic_sets_shared_and_writes_audit(db: Database, manager: MemoryManager):
    episodic = EpisodicMemory(db)
    memory_id = episodic.save("写作私有 阈值配置 蓝色优先", importance=5, agent_id=AGENT_WRITER)

    result = manager.promote_to_shared(memory_id)

    assert result["status"] == "promoted"
    assert result["previous_agent_id"] == AGENT_WRITER
    assert result["memory_type"] == "episodic"
    assert _agent_of(db, "memories_episodic", memory_id) is None

    rows = _evolution_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["memory_type"] == "episodic"
    assert row["memory_id"] == memory_id
    assert row["operation"] == "promote"
    assert AGENT_WRITER in row["reason"]
    assert row["created_at"] > 0


def test_promote_semantic_sets_shared_and_writes_audit(db: Database, manager: MemoryManager):
    semantic = SemanticMemory(db)
    memory_id = semantic.save("写作私有知识 阈值配置 蓝色优先", agent_id=AGENT_WRITER)

    result = manager.promote_to_shared(memory_id)

    assert result["status"] == "promoted"
    assert result["memory_type"] == "semantic"
    assert _agent_of(db, "memories_semantic", memory_id) is None
    assert len(_evolution_rows(db)) == 1


def test_promoted_memory_becomes_visible_to_other_agent(db: Database, manager: MemoryManager):
    """提升后另一专家能读到（原私有不可见）—— 共享层的核心语义。"""
    episodic = EpisodicMemory(db)
    memory_id = episodic.save("写作私有 阈值配置 蓝色优先", importance=5, agent_id=AGENT_WRITER)

    assert memory_id not in {row["id"] for row in episodic.search("阈值配置", agent_id=AGENT_CODER)}

    manager.promote_to_shared(memory_id)

    assert memory_id in {row["id"] for row in episodic.search("阈值配置", agent_id=AGENT_CODER)}


def test_promote_already_shared_is_idempotent(db: Database, manager: MemoryManager):
    episodic = EpisodicMemory(db)
    memory_id = episodic.save("共享偏好 阈值配置 绿色优先", importance=5)

    result = manager.promote_to_shared(memory_id)

    assert result["status"] == "already_shared"
    assert result["previous_agent_id"] is None
    assert _evolution_rows(db) == []


def test_promote_unknown_memory_returns_not_found(db: Database, manager: MemoryManager):
    result = manager.promote_to_shared("no-such-memory")

    assert result["status"] == "not_found"
    assert _evolution_rows(db) == []


def test_promote_respects_memory_type_filter(db: Database, manager: MemoryManager):
    episodic = EpisodicMemory(db)
    semantic = SemanticMemory(db)
    episodic_id = episodic.save("情景私有 阈值配置", importance=5, agent_id=AGENT_WRITER)
    semantic_id = semantic.save("语义私有 阈值配置", agent_id=AGENT_WRITER)

    missed = manager.promote_to_shared(episodic_id, memory_type="semantic")
    assert missed["status"] == "not_found"
    assert _agent_of(db, "memories_episodic", episodic_id) == AGENT_WRITER

    hit = manager.promote_to_shared(semantic_id, memory_type="semantic")
    assert hit["status"] == "promoted"
    assert _agent_of(db, "memories_semantic", semantic_id) is None


def test_promote_rolls_back_when_audit_write_fails(db: Database, manager: MemoryManager):
    """审计写失败必须整体回滚 —— 绝不留下"已公开但无记录"的记忆。"""
    episodic = EpisodicMemory(db)
    memory_id = episodic.save("写作私有 阈值配置", importance=5, agent_id=AGENT_WRITER)

    conn = db.get_connection()
    conn.execute("DROP TABLE memories_evolution_log")
    conn.commit()

    with pytest.raises(sqlite3.DatabaseError):
        manager.promote_to_shared(memory_id)

    assert _agent_of(db, "memories_episodic", memory_id) == AGENT_WRITER


# ---------- purge：专家删除级联清理 ----------


def test_purge_removes_only_that_agents_private_rows(db: Database, manager: MemoryManager):
    episodic = EpisodicMemory(db)
    semantic = SemanticMemory(db)

    e_writer = episodic.save("写作私有 阈值配置", importance=5, agent_id=AGENT_WRITER)
    e_coder = episodic.save("编码私有 阈值配置", importance=5, agent_id=AGENT_CODER)
    e_shared = episodic.save("共享偏好 阈值配置", importance=5)
    s_writer = semantic.save("写作私有知识 阈值配置", agent_id=AGENT_WRITER)
    s_shared = semantic.save("共享用户知识 阈值配置")

    result = manager.purge_agent_memories(AGENT_WRITER)

    assert result["episodic"] == 1
    assert result["semantic"] == 1
    assert set(result["memory_ids"]) == {e_writer, s_writer}

    # 情景层软删除：行仍在，但读路径按 is_valid 过滤 → 不可见
    visible = {row["id"] for row in episodic.search("阈值配置", agent_id=AGENT_WRITER)}
    assert e_writer not in visible
    # 语义层硬删除
    assert _agent_of(db, "memories_semantic", s_writer) is None
    # 其它专家与共享层不受影响
    assert _agent_of(db, "memories_episodic", e_coder) == AGENT_CODER
    assert _agent_of(db, "memories_episodic", e_shared) is None
    assert _agent_of(db, "memories_semantic", s_shared) is None


def test_purge_clears_vector_entries_across_vector_tables(db: Database, manager: MemoryManager):
    """向量表清扫必须覆盖非默认嵌入维度的表（store.delete 只清 memories_vec）。"""
    episodic = EpisodicMemory(db)
    memory_id = episodic.save("写作私有 阈值配置", importance=5, agent_id=AGENT_WRITER)

    conn = db.get_connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memories_vec_512 "
        "(memory_id TEXT, memory_type TEXT, session_id TEXT)"
    )
    conn.execute(
        "INSERT INTO memories_vec_512 (memory_id, memory_type, session_id) VALUES (?, ?, ?)",
        (memory_id, "episodic", "session-1"),
    )
    conn.commit()

    result = manager.purge_agent_memories(AGENT_WRITER)

    remaining = conn.execute(
        "SELECT memory_id FROM memories_vec_512 WHERE memory_id = ?", (memory_id,)
    ).fetchall()
    assert remaining == []
    assert result["vector"] >= 1


def test_purge_unknown_agent_is_noop(db: Database, manager: MemoryManager):
    result = manager.purge_agent_memories("specialist-ghost")

    assert result == {"episodic": 0, "semantic": 0, "vector": 0, "memory_ids": []}


def test_purge_empty_agent_id_is_noop(db: Database, manager: MemoryManager):
    result = manager.purge_agent_memories("")

    assert result == {"episodic": 0, "semantic": 0, "vector": 0, "memory_ids": []}


# ---------- HTTP：POST /memory/{id}/promote ----------


class _FakeManager:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def promote_to_shared(self, memory_id, memory_type=None, reason="user_promote"):
        self.calls.append((memory_id, memory_type, reason))
        return self.result


def test_promote_route_returns_manager_result(monkeypatch):
    manager = _FakeManager(
        {
            "status": "promoted",
            "memory_id": "m1",
            "memory_type": "episodic",
            "previous_agent_id": AGENT_WRITER,
        }
    )
    monkeypatch.setattr(memory_routes, "get_memory_manager", lambda: manager)

    out = memory_routes.promote_memory(
        "m1", memory_routes.MemoryPromoteRequest(memory_type="episodic", reason="ui_promote")
    )

    assert out["status"] == "promoted"
    assert manager.calls == [("m1", "episodic", "ui_promote")]


def test_promote_route_404_when_memory_missing(monkeypatch):
    manager = _FakeManager(
        {
            "status": "not_found",
            "memory_id": "ghost",
            "memory_type": "",
            "previous_agent_id": None,
        }
    )
    monkeypatch.setattr(memory_routes, "get_memory_manager", lambda: manager)

    with pytest.raises(HTTPException) as excinfo:
        memory_routes.promote_memory("ghost", memory_routes.MemoryPromoteRequest())

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["type"] == "memory_not_found"


def test_promote_route_422_on_invalid_memory_type():
    with pytest.raises(HTTPException) as excinfo:
        memory_routes.promote_memory("m1", memory_routes.MemoryPromoteRequest(memory_type="working"))

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["type"] == "invalid_memory_type"
