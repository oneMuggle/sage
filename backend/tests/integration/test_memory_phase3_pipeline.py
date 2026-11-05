"""Phase 3 集成测试：主题簇巩固 + 低质量记忆清理的端到端效果。

Task 3.1–3.4 的单测各自覆盖提示词门槛、聚类、评分器与失效路径，但没有
验证它们在**真实 SQLite + 完整任务流程**上的组合结果。本文件驱动：

1. ``MemoryReflectionTask.run()``：同分类相似记忆 → 一条主题摘要
   （``importance=7`` / ``memory_type=summary``），原始记忆保持有效；
   重复运行不产生重复摘要。
2. LLM 判 INVALIDATE 的行不参与后续摘要（避免把已被否定的事实又写一遍）。
3. ``MemoryPruningTask.run_async()``：质量差 **且** 长期未访问的行被
   软失效（``is_valid=0`` + ``invalid_at``），而近期访问过、价值高、
   带 ``environment`` 标签的行全部保留；物理删除计数保持 0。
4. 清理幂等：第二次运行不再失效、不再写日志。
"""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.scheduler.evolution import MemoryPruningTask, MemoryReflectionTask
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.integration

SESSION = "s1"
NOW_MS = int(time.time() * 1000)
DAY_MS = 86_400_000

#: 两两字面相似度 0.90 —— 落在主题簇阈值（0.75）之上、启发式去重（0.97）之下
TOPIC_A = "用户偏好使用 Python 编写后端服务"
TOPIC_B = "用户偏好使用 Python 编写后端接口"
TOPIC_C = "用户偏好使用 Python 编写后端脚本"
SUMMARY = "用户偏好使用 Python 编写后端服务、接口与脚本。"
CATEGORY = "user_pref"

BAD_CONTENT = "嗯..."


class PromptAwareLLM:
    """按提示词类型回话：整理操作用 ``ops_reply``，归纳请求用 ``summary``。

    ``MemoryReflectionTask._chat`` 先按 ``Message`` 对象调用，假模型只需
    暴露 ``chat(messages)`` 并返回带 ``content`` 的对象。
    """

    def __init__(self, ops_reply: str = "[]", summary: str = SUMMARY) -> None:
        self.ops_reply = ops_reply
        self.summary = summary
        self.prompts: list = []

    async def chat(self, messages):
        prompt = messages[0].content
        self.prompts.append(prompt)
        if "请归纳" in prompt:
            return SimpleNamespace(content=self.summary)
        return SimpleNamespace(content=self.ops_reply)


@pytest.fixture()
def db(tmp_db_path: str) -> Database:
    d = Database(db_path=tmp_db_path)
    d.init_db()
    ensure_session(d, SESSION)
    return d


@pytest.fixture()
def manager(db: Database) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


def _force_literal_similarity(monkeypatch) -> None:
    """固定走字面相似度 —— 本机若装了 ONNX 模型，聚类结果会随模型漂移。"""
    import backend.memory.embedder_factory as factory

    monkeypatch.setattr(factory, "get_shared_embedder", lambda: None)


def _save_topics(manager: MemoryManager) -> list:
    return [
        manager.episodic.save(
            content=text,
            importance=6,
            memory_category=CATEGORY,
            scope="user",
        )
        for text in (TOPIC_A, TOPIC_B, TOPIC_C)
    ]


def _summary_rows(db: Database) -> list:
    cursor = db.get_connection().execute(
        "SELECT id, content, importance, memory_type, memory_category, invalid_at "
        "FROM memories_episodic WHERE memory_category = ?",
        (f"{CATEGORY}_summary",),
    )
    return [dict(row) for row in cursor.fetchall()]


def _row(db: Database, memory_id: str) -> dict:
    row = db.get_connection().execute(
        "SELECT * FROM memories_episodic WHERE id = ?", (memory_id,)
    ).fetchone()
    return dict(row) if row else {}


# ============================ 主题簇巩固 ============================


def test_consolidation_creates_topic_summary(db, manager, monkeypatch):
    _force_literal_similarity(monkeypatch)
    source_ids = _save_topics(manager)
    task = MemoryReflectionTask(db=db, memory_manager=manager, llm_client=PromptAwareLLM())

    stats = task.run()

    assert stats["scanned"] >= 3
    assert stats["deduped"] == 0  # 相似度 0.90 < 0.97，启发式去重不动
    assert stats["consolidated"] == 1

    summaries = _summary_rows(db)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["content"] == SUMMARY
    assert summary["importance"] == 7
    assert summary["memory_type"] == "summary"
    assert summary["invalid_at"] is None
    # 原始记忆保持有效 —— 摘要是补充入口，不取代原始事实
    for memory_id in source_ids:
        assert _row(db, memory_id)["invalid_at"] is None
        assert _row(db, memory_id)["is_valid"] == 1

    # 来源 id 记入记忆级审计日志（schema 无来源列，复用 before_content）
    audit = db.get_connection().execute(
        "SELECT * FROM memories_evolution_log "
        "WHERE operation = 'consolidate_summary'"
    ).fetchone()
    assert audit is not None
    for memory_id in source_ids:
        assert memory_id in audit["before_content"]

    task_log = db.get_connection().execute(
        "SELECT metrics_json FROM evolution_log "
        "WHERE evolution_type = 'memory_reflection' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert json.loads(task_log["metrics_json"])["consolidated"] == 1


def test_consolidation_is_idempotent(db, manager, monkeypatch):
    _force_literal_similarity(monkeypatch)
    _save_topics(manager)
    llm = PromptAwareLLM()
    task = MemoryReflectionTask(db=db, memory_manager=manager, llm_client=llm)

    first = task.run()
    second = task.run()

    assert first["consolidated"] == 1
    assert second["consolidated"] == 0
    assert len(_summary_rows(db)) == 1


def test_invalidated_rows_do_not_enter_summary(db, manager, monkeypatch):
    """LLM 判过时的行不参与摘要 —— 否则摘要会把被否定的事实再写一遍。"""
    _force_literal_similarity(monkeypatch)
    _save_topics(manager)
    task = MemoryReflectionTask(
        db=db,
        memory_manager=manager,
        llm_client=PromptAwareLLM(
            ops_reply='[{"op": "INVALIDATE", "id": 1, "reason": "过时"}]'
        ),
    )

    stats = task.run()

    assert stats["invalidated"] == 1
    # 3 条里失效 1 条 → 剩 2 条，低于 MIN_CLUSTER_SIZE，不生成摘要
    assert stats["consolidated"] == 0
    assert _summary_rows(db) == []


# ============================ 低质量记忆清理 ============================


def _insert_row(
    db: Database,
    *,
    content: str,
    importance: int = 5,
    created_at: int,
    accessed_at=None,
    access_count: int = 0,
    tags: str = "[]",
    is_valid: int = 1,
) -> str:
    memory_id = str(uuid.uuid4())
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO memories_episodic
        (id, session_id, content, summary, memory_type, importance, source, tags,
         created_at, accessed_at, access_count, is_valid, scope, memory_category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'user', NULL)
        """,
        (
            memory_id,
            None,
            content,
            content[:50],
            "conversation",
            importance,
            "test",
            tags,
            created_at,
            accessed_at,
            access_count,
            is_valid,
        ),
    )
    conn.commit()
    return memory_id


def _seed_prune_candidates(db: Database) -> dict:
    stale = NOW_MS - 200 * DAY_MS
    return {
        # 质量差 + 长期未访问 → 唯一应被软失效的行
        "bad": _insert_row(
            db, content=BAD_CONTENT, importance=1, created_at=stale, access_count=0
        ),
        # 同样写得差，但刚创建 → 保留（可能只是还没被检索到）
        "recent": _insert_row(
            db,
            content=BAD_CONTENT,
            importance=1,
            created_at=NOW_MS,
            accessed_at=NOW_MS,
        ),
        # 创建很久但最近被访问过 → 保留
        "used": _insert_row(
            db,
            content=BAD_CONTENT,
            importance=1,
            created_at=stale,
            accessed_at=NOW_MS - DAY_MS,
            access_count=1,
        ),
        # 陈旧但高价值 → 保留
        "valuable": _insert_row(
            db,
            content="用户在项目中强制要求所有 Python 代码使用 ruff 格式化并开启类型注解检查",
            importance=9,
            created_at=NOW_MS - 400 * DAY_MS,
            access_count=10,
        ),
        # 环境解决方案豁免 → 保留
        "environment": _insert_row(
            db,
            content=BAD_CONTENT,
            importance=1,
            created_at=stale,
            tags='["environment"]',
        ),
    }


def test_prune_soft_invalidates_only_low_quality_stale(db):
    ids = _seed_prune_candidates(db)
    task = MemoryPruningTask(db=db)

    deleted = task.run()

    assert deleted == 0  # 只软失效，不物理删除
    pruned = _row(db, ids["bad"])
    assert pruned["is_valid"] == 0
    assert pruned["invalid_at"] is not None
    # 其余四类全部保留
    for key in ("recent", "used", "valuable", "environment"):
        row = _row(db, ids[key])
        assert row["is_valid"] == 1, key
        assert row["invalid_at"] is None, key

    logs = db.get_connection().execute(
        "SELECT * FROM memories_evolution_log WHERE operation = 'prune_quality'"
    ).fetchall()
    assert len(logs) == 1
    assert logs[0]["memory_id"] == ids["bad"]
    assert logs[0]["reason"] == "memory_pruning:low_quality"
    assert logs[0]["after_content"].startswith("quality=")

    task_log = db.get_connection().execute(
        "SELECT metrics_json FROM evolution_log "
        "WHERE evolution_type = 'memory_pruning' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    metrics = json.loads(task_log["metrics_json"])
    assert metrics["memories_quality_pruned"] == 1
    assert metrics["memories_deleted"] == 0


def test_prune_quality_is_idempotent(db):
    ids = _seed_prune_candidates(db)
    task = MemoryPruningTask(db=db)

    task.run()
    first_pruned_at = _row(db, ids["bad"])["invalid_at"]
    task.run()

    # 已失效行被排除在扫描之外，第二次不再改写
    assert _row(db, ids["bad"])["invalid_at"] == first_pruned_at
    logs = db.get_connection().execute(
        "SELECT COUNT(*) FROM memories_evolution_log WHERE operation = 'prune_quality'"
    ).fetchone()[0]
    assert logs == 1
