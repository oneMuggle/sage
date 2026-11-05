"""M3-Task 3 — 专家记忆策略 + MemoryManager agent 维度隔离测试。

契约：

- ``MemoryPolicy`` pydantic v1/v2 双兼容，``extra='forbid'``；
- ``parse_memory_policy``：None/实例/dict/JSON 字符串 → MemoryPolicy；
  坏 JSON 与非法枚举 → 降级为默认策略并告警（fail-safe）。
- ``resolve_write_agent_id``：策略无 / write_scope='specialist' → 当前
  专家；``project`` / ``user`` → None（共享层）。
- ``includes_private_reads``：read_scopes 含 ``specialist`` 时私有可见。
- Manager API：``remember / memorize / aremember / recall /
  search_memories / get_context / get_context_with_hits / resolve_conflicts /
  memorize_with_conflict_check`` 正确传递 ``agent_id`` 与 ``include_private``；
  ``delete_memory`` 跨专家私有行保护（agent_id 给定时拒删他人私有行）。
- Manager 构造可注入 ``memory_policy``，策略覆盖读写。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agents.memory_policy import (
    MemoryPolicy,
    includes_private_reads,
    parse_memory_policy,
    resolve_write_agent_id,
)
from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory

pytestmark = pytest.mark.unit

AGENT_WRITER = "specialist-writer"
AGENT_CODER = "specialist-coder"

QUERY = "阈值配置"


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


@pytest.fixture()
def policy_manager(db: Database) -> MemoryManager:
    """默认写入归「specialist」但读侧剔除私有行（策略覆盖）。"""
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
        memory_policy={
            "read_scopes": ["project", "user"],  # 缺 specialist
            "write_scope": "specialist",
            "auto_extract": True,
        },
    )


# ---------- MemoryPolicy 模型 ----------


def test_memory_policy_defaults_match_pre_m3() -> None:
    policy = MemoryPolicy()
    assert policy.read_scopes == ["specialist", "project", "user"]
    assert policy.write_scope == "specialist"
    assert policy.auto_extract is True
    assert policy.retention_days is None


def test_memory_policy_rejects_extra_fields() -> None:
    """pydantic v1/v2 双兼容：``extra='forbid'`` 必须生效。"""
    with pytest.raises(ValidationError):
        MemoryPolicy(bogus_key="nope")


def test_parse_policy_from_none_dict_json_instance() -> None:
    assert parse_memory_policy(None) == MemoryPolicy()
    assert parse_memory_policy({}) == MemoryPolicy()
    assert parse_memory_policy('{"write_scope": "project"}').write_scope == "project"
    assert parse_memory_policy(MemoryPolicy(write_scope="user")).write_scope == "user"


def test_parse_policy_bad_json_falls_back_to_default() -> None:
    bad = parse_memory_policy("{not json")
    assert bad == MemoryPolicy()


def test_parse_policy_invalid_enum_falls_back_to_default() -> None:
    bad = parse_memory_policy({"write_scope": "bogus"})
    assert bad == MemoryPolicy()


def test_helpers_default_none_is_unfiltered() -> None:
    """未配置策略时，读始终含私有、写沿用显式 agent。"""
    assert includes_private_reads(None) is True
    assert resolve_write_agent_id(None, AGENT_WRITER) == AGENT_WRITER
    assert resolve_write_agent_id(None, None) is None


def test_helpers_policy_narrows_to_shared_write() -> None:
    """write_scope != specialist 时 resolve 归零为 None（共享层）。"""
    policy = MemoryPolicy(write_scope="project")
    assert resolve_write_agent_id(policy, AGENT_WRITER) is None


def test_helpers_policy_excludes_private_reads() -> None:
    policy = MemoryPolicy(read_scopes=["project", "user"])
    assert includes_private_reads(policy) is False


# ---------- MemoryManager API：写默认、读过滤 ----------


def test_manager_remember_writes_shared_by_default(manager: MemoryManager, db) -> None:
    mid = manager.remember(f"默认共享 阈值配置 {QUERY}")

    row = db.get_connection().execute(
        "SELECT agent_id FROM memories_episodic WHERE id = ?", (mid,)
    ).fetchone()
    assert row["agent_id"] is None


def test_manager_memorize_honors_agent_id(manager: MemoryManager, db) -> None:
    mid = manager.memorize(
        f"写作私有 阈值配置 {QUERY}",
        memory_type="episodic",
        importance=5,
        agent_id=AGENT_WRITER,
    )
    assert mid is not None

    row = db.get_connection().execute(
        "SELECT agent_id FROM memories_episodic WHERE id = ?", (mid,)
    ).fetchone()
    assert row["agent_id"] == AGENT_WRITER


def test_manager_recall_isolates_by_agent(manager: MemoryManager) -> None:
    writer_id = manager.memorize(
        f"写作私有 阈值配置 {QUERY}", memory_type="episodic", agent_id=AGENT_WRITER
    )
    coder_id = manager.memorize(
        f"编码私有 阈值配置 {QUERY}", memory_type="episodic", agent_id=AGENT_CODER
    )
    shared_id = manager.memorize(f"共享偏好 阈值配置 {QUERY}", memory_type="episodic")

    writer_hits = {r["id"] for r in manager.recall(QUERY, agent_id=AGENT_WRITER)["episodic"]}
    coder_hits = {r["id"] for r in manager.recall(QUERY, agent_id=AGENT_CODER)["episodic"]}
    # 私有行只归本人，共享行双方都可见
    assert writer_hits - coder_hits == {writer_id}
    assert coder_hits - writer_hits == {coder_id}
    assert writer_hits & coder_hits == {shared_id}


def test_manager_include_private_false_shows_shared_only(manager: MemoryManager) -> None:
    writer_id = manager.memorize(f"写作私有 阈值配置 {QUERY}", memory_type="episodic", agent_id=AGENT_WRITER)
    shared_id = manager.memorize(f"共享偏好 阈值配置 {QUERY}", memory_type="episodic")

    hits = {
        r["id"]
        for r in manager.recall(QUERY, agent_id=AGENT_WRITER, include_private=False)[
            "episodic"
        ]
    }
    assert shared_id in hits
    assert writer_id not in hits


def test_manager_get_context_isolates_by_agent(manager: MemoryManager) -> None:
    writer_id = manager.memorize(
        f"写作私有 阈值配置 {QUERY}", memory_type="episodic", agent_id=AGENT_WRITER
    )
    coder_id = manager.memorize(
        f"编码私有 阈值配置 {QUERY}", memory_type="episodic", agent_id=AGENT_CODER
    )
    shared_id = manager.memorize(f"共享偏好 阈值配置 {QUERY}", memory_type="episodic")

    _, writer_hits = manager.get_context_with_hits(agent_id=AGENT_WRITER, limit=20)
    _, coder_hits = manager.get_context_with_hits(agent_id=AGENT_CODER, limit=20)
    # episodic 层行在 get_context_with_hits 中以 "conversation" memory_type 呈现
    writer_ids = {h["id"] for h in writer_hits}
    coder_ids = {h["id"] for h in coder_hits}
    assert shared_id in writer_ids
    assert shared_id in coder_ids
    assert writer_ids - coder_ids == {writer_id}
    assert coder_ids - writer_ids == {coder_id}


def test_manager_search_memories_isolates_by_agent(manager: MemoryManager) -> None:
    writer_id = manager.memorize(f"写作私有 阈值配置 {QUERY}", memory_type="semantic", agent_id=AGENT_WRITER)
    coder_id = manager.memorize(f"编码私有 阈值配置 {QUERY}", memory_type="semantic", agent_id=AGENT_CODER)
    shared_id = manager.memorize(f"共享偏好 阈值配置 {QUERY}", memory_type="semantic")

    writer_rows = {
        r["id"] for r in manager.search_memories(QUERY, agent_id=AGENT_WRITER)
    }
    coder_rows = {r["id"] for r in manager.search_memories(QUERY, agent_id=AGENT_CODER)}
    assert writer_id in writer_rows
    assert coder_id not in writer_rows
    assert shared_id in writer_rows
    assert coder_id in coder_rows
    assert shared_id in coder_rows


# ---------- MemoryManager 策略覆盖 ----------


def test_policy_manager_write_stays_private(policy_manager: MemoryManager, db) -> None:
    mid = policy_manager.memorize(
        f"写作私有 阈值配置 {QUERY}",
        memory_type="episodic",
        agent_id=AGENT_WRITER,
    )
    row = db.get_connection().execute(
        "SELECT agent_id FROM memories_episodic WHERE id = ?", (mid,)
    ).fetchone()
    assert row["agent_id"] == AGENT_WRITER


def test_policy_manager_read_hides_private_even_with_agent(
    policy_manager: MemoryManager,
) -> None:
    """read_scopes 缺 specialist → 即使传入 agent_id，私有行也不可见。"""
    writer_id = policy_manager.memorize(
        f"写作私有 阈值配置 {QUERY}",
        memory_type="episodic",
        agent_id=AGENT_WRITER,
    )
    shared_id = policy_manager.memorize(f"共享偏好 阈值配置 {QUERY}", memory_type="episodic")

    writer_hits = {
        r["id"]
        for r in policy_manager.recall(QUERY, agent_id=AGENT_WRITER)["episodic"]
    }
    assert writer_id not in writer_hits
    assert shared_id in writer_hits


def test_policy_manager_shared_write_when_scope_not_specialist(db) -> None:
    """write_scope='user' → 即使显式给 agent_id，仍落共享层。"""
    manager = MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
        memory_policy={"write_scope": "user"},
    )
    mid = manager.memorize(
        f"强制共享 阈值配置 {QUERY}",
        memory_type="episodic",
        agent_id=AGENT_WRITER,
    )
    row = db.get_connection().execute(
        "SELECT agent_id FROM memories_episodic WHERE id = ?", (mid,)
    ).fetchone()
    assert row["agent_id"] is None


# ---------- 跨专家删除保护 ----------


def test_manager_delete_memory_refuses_other_agent_private(
    manager: MemoryManager,
) -> None:
    writer_id = manager.memorize(
        f"写作私有 阈值配置 {QUERY}",
        memory_type="episodic",
        agent_id=AGENT_WRITER,
    )

    # 编码专家试图删除写专家的私有行 → 拒绝
    assert manager.delete_memory(writer_id, "episodic", agent_id=AGENT_CODER) is False
    # 写专家自己删除 → 允许
    assert manager.delete_memory(writer_id, "episodic", agent_id=AGENT_WRITER) is True


def test_manager_delete_memory_shared_admin_path(manager: MemoryManager) -> None:
    shared_id = manager.memorize(f"共享偏好 阈值配置 {QUERY}", memory_type="episodic")
    # 管理口径删除共享行（agent_id=None）→ 允许
    assert manager.delete_memory(shared_id, "episodic", agent_id=None) is True
    # 行已确实消失
    assert manager.episodic.get_by_id(shared_id) is None


# ---------- 冲突消解 agent 透传 ----------


def test_manager_resolve_conflicts_honors_agent_id(manager: MemoryManager) -> None:
    """写入前冲突判定：agent_id 给定 → 候选范围 = 私有 ∪ 共享。"""
    writer_id = manager.memorize(
        f"写作私有 阈值配置 {QUERY} 蓝色优先",
        memory_type="episodic",
        agent_id=AGENT_WRITER,
    )
    coder_id = manager.memorize(
        f"编码私有 阈值配置 {QUERY} 红色优先",
        memory_type="episodic",
        agent_id=AGENT_CODER,
    )

    # 写专家再写近似内容 → 命中自己的私有行（同归属），候选非空
    decision_writer = manager.resolve_conflicts(
        f"写作私有 阈值配置 {QUERY} 蓝色优先",
        agent_id=AGENT_WRITER,
    )
    writer_targets = {c.id for c in decision_writer.targets}
    assert writer_id in writer_targets
    assert coder_id not in writer_targets
