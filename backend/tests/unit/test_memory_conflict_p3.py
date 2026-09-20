"""P3 冲突消解（Mem0 风格 ADD/UPDATE/NOOP + Zep 风格时间有效区）回归测试。

覆盖:
- schema: invalid_at / supersedes_id 列
- 存储层: invalidate() 的读路径隐藏（search/get_recent/count/exists, get_by_id 保留）
- MemoryConflictResolver: NOOP/UPDATE/ADD 判定、归属对齐（跨项目/跨 scope 不误伤）
- apply_update: supersedes 链 + scope/project_key 继承
- llm_decide 钩子（合法输出生效 / 非法输出回退启发式）
- MemoryManager.memorize_with_conflict_check
- MemoryAdapter.store() 端到端接线（NOOP 复用 ID / UPDATE 使旧行失效）
- scope.is_row_visible 对 invalid 行的旁路兜底
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory import scope as memory_scope
from backend.memory.conflict import (
    OP_ADD,
    OP_NOOP,
    OP_UPDATE,
    MemoryConflictResolver,
    _similarity,
)
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit

PROJ_A = "/tmp/p3-proj-a"
PROJ_B = "/tmp/p3-proj-b"

# 相似度（SequenceMatcher, 见 test_thresholds_of_fixture_pairs）:
#   A vs D ≈ 0.988 → NOOP 区（>=0.97）
#   A vs B ≈ 0.892 → UPDATE 区（[0.78, 0.97)）
#   A vs C ≈ 0.215 → ADD 区
A = "用户在项目里约定所有 Python 代码使用 ruff 格式化并且强制要求类型注解"
B = "用户在项目里约定所有 Python 代码使用 black 格式化并且强制要求类型注解"
C = "用户最近开始尝试使用 Rust 编写命令行小工具"
D = "用户在项目里约定所有 Python 代码使用 ruff 格式化并且强制要求类型注解。"


def _bind(db: Database, session_id: str, workspace_path: str) -> None:
    ensure_session(db, session_id)
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
    # memories_episodic.session_id 有 FK 约束, 先建好夹具会话
    for sid in ("s1", "s-proj", "s-a", "s-b"):
        ensure_session(d, sid)
    return d


@pytest.fixture()
def manager(db: Database) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


# ---------- schema / 阈值前提 ----------


def test_schema_has_p3_columns(db: Database) -> None:
    conn = db.get_connection()
    for table in ("memories_episodic", "memories_semantic"):
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert "invalid_at" in cols, table
        assert "supersedes_id" in cols, table


def test_thresholds_of_fixture_pairs() -> None:
    """判定测试的前提: 夹具对的相似度落在预期区间。"""
    assert _similarity(A, D) >= 0.97
    assert 0.78 <= _similarity(A, B) < 0.97
    assert _similarity(A, C) < 0.78


# ---------- 存储层 invalidate ----------


def test_episodic_invalidate_hides_from_read_paths(db: Database) -> None:
    epi = EpisodicMemory(db)
    mid = epi.save(content=A, importance=6, session_id="s1")
    assert epi.count() == 1
    assert epi.invalidate(mid) is True
    # 二次 invalidate 不生效（已失效行）
    assert epi.invalidate(mid) is False

    assert epi.search("ruff", session_id="s1") == []
    assert epi.get_recent(limit=10, session_id="s1") == []
    assert epi.count() == 0

    # get_by_id 仍可取回（审计 / supersedes 链追溯）
    row = epi.get_by_id(mid)
    assert row is not None
    assert row["invalid_at"] is not None
    assert row["is_valid"] == 1  # 失效 ≠ 删除


def test_semantic_invalidate_hides_from_read_paths(db: Database) -> None:
    sem = SemanticMemory(db)
    mid = sem.save(content=A, tags=["test"], session_id="s1")
    assert sem.count() == 1
    assert sem.invalidate(mid) is True

    assert sem.get_recent(limit=10, session_id="s1") == []
    assert sem.count() == 0

    row = sem.get_by_id(mid)
    assert row is not None
    assert row["invalid_at"] is not None


def test_save_supersedes_id_persisted(db: Database) -> None:
    epi = EpisodicMemory(db)
    old = epi.save(content=A, importance=6, session_id="s1")
    new = epi.save(content=B, importance=6, session_id="s1", supersedes_id=old)
    row = epi.get_by_id(new)
    assert row["supersedes_id"] == old


# ---------- resolver 判定 ----------


def test_resolve_noop_update_add(manager: MemoryManager) -> None:
    mid = manager.memorize(A, memory_type="episodic", importance=6, session_id="s1")

    resolver = manager.get_conflict_resolver()
    assert resolver.resolve(D, session_id="s1").op == OP_NOOP
    assert resolver.resolve(B, session_id="s1").op == OP_UPDATE
    assert resolver.resolve(C, session_id="s1").op == OP_ADD

    noop = resolver.resolve(D, session_id="s1")
    assert noop.superseded_ids == [mid]


def test_resolve_empty_content_is_add(manager: MemoryManager) -> None:
    assert manager.resolve_conflicts("   ").op == OP_ADD


def test_apply_update_inherits_scope_and_chains(db: Database, manager: MemoryManager) -> None:
    _bind(db, "s-proj", PROJ_A)
    old = manager.memorize(
        A, memory_type="episodic", importance=6, session_id="s-proj",
        scope="project", project_key=PROJ_A,
    )
    resolver = manager.get_conflict_resolver()
    decision = resolver.resolve(B, session_id="s-proj")
    assert decision.op == OP_UPDATE

    saved: dict = {}

    def save_fn(**kwargs):
        saved.update(kwargs)
        return manager.memorize(**kwargs)

    new_id, op = resolver.apply_update(
        decision, save_fn, content=B, memory_type="episodic",
        importance=6, session_id="s-proj",
    )
    assert op == OP_UPDATE
    assert new_id
    row = manager.episodic.get_by_id(new_id)
    assert row["scope"] == "project"
    assert row["project_key"] == PROJ_A
    assert row["supersedes_id"] == old
    assert manager.episodic.get_by_id(old)["invalid_at"] is not None


def test_cross_project_writes_never_supersede(db: Database, manager: MemoryManager) -> None:
    _bind(db, "s-a", PROJ_A)
    _bind(db, "s-b", PROJ_B)
    old = manager.memorize(
        A, memory_type="episodic", importance=6, session_id="s-a",
        scope="project", project_key=PROJ_A,
    )
    # B 与 A 高相似, 但归属不同项目 → ADD, 且 A 保持有效
    decision = manager.resolve_conflicts(B, session_id="s-b")
    assert decision.op == OP_ADD

    new_id, op = manager.memorize_with_conflict_check(
        B, memory_type="episodic", importance=6, session_id="s-b",
        scope="project", project_key=PROJ_B,
    )
    assert op == OP_ADD
    assert new_id != old
    assert manager.episodic.get_by_id(old)["invalid_at"] is None


def test_scope_mismatch_user_vs_project_is_add(db: Database, manager: MemoryManager) -> None:
    _bind(db, "s-a", PROJ_A)
    # user 归属的既有记忆, 不应被 project 归属的写入取代
    manager.memorize(A, memory_type="episodic", importance=6, session_id=None, scope="user")
    decision = manager.resolve_conflicts(B, session_id="s-a", scope="project")
    assert decision.op == OP_ADD


def test_llm_hook_overrides_and_falls_back(manager: MemoryManager, db: Database) -> None:
    manager.memorize(A, memory_type="episodic", importance=6, session_id="s1")
    by_id = {r["id"]: r for r in manager.episodic.search("ruff", session_id="s1")}
    target = list(by_id)[0]

    # 合法 LLM 输出: 对毫不相似的 C 也判 NOOP
    resolver = MemoryConflictResolver(
        manager.episodic,
        manager.semantic,
        llm_decide=lambda content, cands: [{"op": "NOOP", "target_id": target}],
    )
    assert resolver.resolve(C, session_id="s1").op == OP_NOOP

    # 非法输出（未知 op）→ 回退启发式, A/B 仍是 UPDATE
    resolver_bad = MemoryConflictResolver(
        manager.episodic,
        manager.semantic,
        llm_decide=lambda content, cands: [{"op": "DELETE", "target_id": target}],
    )
    assert resolver_bad.resolve(B, session_id="s1").op == OP_UPDATE


# ---------- manager.memorize_with_conflict_check ----------


def test_memorize_conflict_check_noop_reuses_id(manager: MemoryManager) -> None:
    id1, op1 = manager.memorize_with_conflict_check(A, memory_type="episodic", importance=6, session_id="s1")
    assert op1 == OP_ADD
    assert id1
    id2, op2 = manager.memorize_with_conflict_check(D, memory_type="episodic", importance=6, session_id="s1")
    assert op2 == OP_NOOP
    assert id2 == id1
    assert manager.episodic.count() == 1  # 没有新行


def test_memorize_conflict_check_update_swaps_rows(manager: MemoryManager) -> None:
    id1, _ = manager.memorize_with_conflict_check(A, memory_type="episodic", importance=6, session_id="s1")
    id2, op = manager.memorize_with_conflict_check(B, memory_type="episodic", importance=6, session_id="s1")
    assert op == OP_UPDATE
    assert id2
    assert id2 != id1
    assert manager.episodic.get_by_id(id1)["invalid_at"] is not None
    assert manager.episodic.get_by_id(id2)["supersedes_id"] == id1
    # 检索只见新行
    hits = manager.episodic.search("格式化", session_id="s1")
    assert [h["id"] for h in hits] == [id2]


def test_memorize_conflict_check_working_bypasses(manager: MemoryManager) -> None:
    mid, op = manager.memorize_with_conflict_check(
        "短笔记", memory_type="working", importance=3, session_id="s1"
    )
    assert op == OP_ADD
    assert mid.startswith("wm:")


# ---------- MemoryAdapter.store() 端到端 ----------


@pytest.mark.asyncio()
async def test_adapter_store_conflict_pipeline(db: Database) -> None:
    from backend.adapters.out.memory.adapter import MemoryAdapter

    manager = MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )
    adapter = MemoryAdapter(manager)
    adapter.vector_store = None  # 单测不依赖 sqlite-vec

    id1 = await adapter.store(A, "s1", importance=6)
    id_dup = await adapter.store(D, "s1", importance=6)  # NOOP → 复用既有 ID
    assert id_dup == id1
    assert manager.episodic.count() == 1

    id_upd = await adapter.store(B, "s1", importance=6)  # UPDATE → 新行, 旧行失效
    assert id_upd
    assert id_upd != id1
    assert manager.episodic.get_by_id(id1)["invalid_at"] is not None
    assert manager.episodic.count() == 1  # 只剩新行

    id_new = await adapter.store(C, "s1", importance=6)  # ADD
    assert id_new not in (id1, id_upd)
    assert manager.episodic.count() == 2


# ---------- scope.is_row_visible 旁路兜底 ----------


def test_is_row_visible_rejects_invalid_rows() -> None:
    ts = 1_700_000_000_000
    assert memory_scope.is_row_visible({"scope": "user", "invalid_at": ts}, None) is False
    assert memory_scope.is_row_visible({"scope": "user", "invalid_at": None}, None) is True
    assert (
        memory_scope.is_row_visible(
            {"scope": "project", "project_key": PROJ_A, "invalid_at": ts}, PROJ_A
        )
        is False
    )
