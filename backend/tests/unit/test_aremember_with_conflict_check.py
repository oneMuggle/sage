"""aremember_with_conflict_check 回归测试。

覆盖三条路径：
* ADD — 全新事实落 episodic
* NOOP — 字面高度相似（>= 0.97）复用既有 id，不写新行
* UPDATE — 中度相似（[0.78, 0.97)）取代旧行、旧行 invalid_at 落戳
* working bypass — 低重要性短内容直走 working，不经冲突判定

并覆盖失败兜底：resolve / apply_update 抛异常时退回 ADD，不丢事实。
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory.conflict import OP_ADD, OP_NOOP, OP_UPDATE
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


# 与 test_memory_conflict_p3 同一套夹具对（字面相似度已知）:
#   A vs D ≈ 0.988 → NOOP
#   A vs B ≈ 0.892 → UPDATE
#   A vs C ≈ 0.215 → ADD
A = "用户在项目里约定所有 Python 代码使用 ruff 格式化并且强制要求类型注解"
B = "用户在项目里约定所有 Python 代码使用 black 格式化并且强制要求类型注解"
C = "用户最近开始尝试使用 Rust 编写命令行小工具"
D = "用户在项目里约定所有 Python 代码使用 ruff 格式化并且强制要求类型注解。"


@pytest.fixture()
def db(tmp_db_path: str) -> Database:
    d = Database(db_path=tmp_db_path)
    d.init_db()
    ensure_session(d, "s1")
    return d


@pytest.fixture()
def manager(db: Database) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


@pytest.mark.asyncio()
async def test_aremember_conflict_check_add(manager: MemoryManager) -> None:
    mid, op = await manager.aremember_with_conflict_check(
        A, session_id="s1", importance=6, memory_category="project_fact"
    )
    assert op == OP_ADD
    assert mid
    # traceability kwargs 透传到 episodic 行
    row = manager.episodic.get_by_id(mid)
    assert row is not None
    assert row["memory_category"] == "project_fact"
    assert row["importance"] == 6


@pytest.mark.asyncio()
async def test_aremember_conflict_check_noop_reuses_id(manager: MemoryManager) -> None:
    id1, op1 = await manager.aremember_with_conflict_check(
        A, session_id="s1", importance=6
    )
    assert op1 == OP_ADD

    id2, op2 = await manager.aremember_with_conflict_check(
        D, session_id="s1", importance=6
    )
    assert op2 == OP_NOOP
    assert id2 == id1
    assert manager.episodic.count() == 1  # 没有新行


@pytest.mark.asyncio()
async def test_aremember_conflict_check_update_swaps_rows(manager: MemoryManager) -> None:
    id1, _ = await manager.aremember_with_conflict_check(
        A, session_id="s1", importance=6
    )
    id2, op = await manager.aremember_with_conflict_check(
        B, session_id="s1", importance=6
    )
    assert op == OP_UPDATE
    assert id2
    assert id2 != id1
    assert manager.episodic.get_by_id(id1)["invalid_at"] is not None
    assert manager.episodic.get_by_id(id2)["supersedes_id"] == id1


@pytest.mark.asyncio()
async def test_aremember_conflict_check_short_content_writes_episodic(
    manager: MemoryManager,
) -> None:
    """短内容 + 低重要性：classify 为 working，但 aremember 硬编码 conversation → 写 episodic。

    新 API 不支持显式 working 写入（auto-memory 事实都是 episodic/semantic）。
    """
    mid, op = await manager.aremember_with_conflict_check(
        "短笔记", session_id="s1", importance=3
    )
    assert op == OP_ADD
    # aremember 写 episodic（非 wm: 前缀）
    assert mid
    assert not mid.startswith("wm:")
    row = manager.episodic.get_by_id(mid)
    assert row is not None


@pytest.mark.asyncio()
async def test_aremember_conflict_check_resolve_failure_falls_back_to_add(
    manager: MemoryManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """resolve_conflicts 抛异常时退回 ADD，不丢事实。"""
    from backend.memory import manager as manager_module

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated sqlite failure")

    monkeypatch.setattr(manager_module.MemoryManager, "resolve_conflicts", _boom)

    mid, op = await manager.aremember_with_conflict_check(
        A, session_id="s1", importance=6
    )
    assert op == OP_ADD
    assert mid


@pytest.mark.asyncio()
async def test_aremember_conflict_check_preserves_traceability(
    manager: MemoryManager,
) -> None:
    """source_turn_id / source_message_id / memory_category 必须透传到 episodic 行。"""
    mid, _ = await manager.aremember_with_conflict_check(
        A,
        session_id="s1",
        source_turn_id="turn-42",
        source_message_id="msg-99",
        memory_category="user_pref",
        importance=7,
    )
    row = manager.episodic.get_by_id(mid)
    assert row["source_turn_id"] == "turn-42"
    assert row["source_message_id"] == "msg-99"
    assert row["memory_category"] == "user_pref"
    assert row["importance"] == 7
