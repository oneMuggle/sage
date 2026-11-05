"""M3-Task 2 — 存储层专家记忆隔离（agent_id 维度）测试。

契约（记忆隔离验收的最小单元矩阵）：
- 私有行（``agent_id = 专家``）对该专家可见，对其他专家不可见；
- 共享行（``agent_id IS NULL``）对任何专家可见；
- 不传 ``agent_id``（历史调用 / 管理视图）时不限制，行为与 M3 前一致；
- FTS 与 LIKE 两条检索路径、``save`` 与 ``get_recent`` 全覆盖 —— 漏一处即泄漏。
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory import scope as memory_scope
from backend.memory.episodic import EpisodicMemory
from backend.memory.semantic import SemanticMemory

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
def episodic(db: Database) -> EpisodicMemory:
    return EpisodicMemory(db)


@pytest.fixture()
def semantic(db: Database) -> SemanticMemory:
    return SemanticMemory(db)


def _ids(rows) -> set:
    return {row["id"] for row in rows}


# ---------- 情景记忆 ----------


def test_episodic_fts_private_isolated_and_shared_visible(episodic: EpisodicMemory) -> None:
    writer_id = episodic.save("写作私有 阈值配置 蓝色优先", importance=5, agent_id=AGENT_WRITER)
    coder_id = episodic.save("编码私有 阈值配置 红色优先", importance=5, agent_id=AGENT_CODER)
    shared_id = episodic.save("共享偏好 阈值配置 绿色优先", importance=5)

    writer_visible = _ids(episodic.search(QUERY, agent_id=AGENT_WRITER))
    assert writer_id in writer_visible
    assert shared_id in writer_visible
    assert coder_id not in writer_visible

    coder_visible = _ids(episodic.search(QUERY, agent_id=AGENT_CODER))
    assert coder_id in coder_visible
    assert shared_id in coder_visible
    assert writer_id not in coder_visible


def test_episodic_like_path_private_isolated_and_shared_visible(
    episodic: EpisodicMemory,
) -> None:
    """FTS 回退路径（_search_like）同样必须过滤 —— 两条路径漏一条即泄漏。"""
    writer_id = episodic.save("写作私有 阈值配置 蓝色优先", importance=5, agent_id=AGENT_WRITER)
    coder_id = episodic.save("编码私有 阈值配置 红色优先", importance=5, agent_id=AGENT_CODER)
    shared_id = episodic.save("共享偏好 阈值配置 绿色优先", importance=5)

    writer_visible = _ids(episodic._search_like(QUERY, agent_id=AGENT_WRITER))
    assert writer_visible == {writer_id, shared_id}
    coder_visible = _ids(episodic._search_like(QUERY, agent_id=AGENT_CODER))
    assert coder_visible == {coder_id, shared_id}


def test_episodic_search_without_agent_sees_all(episodic: EpisodicMemory) -> None:
    """不传 agent_id（历史调用 / 管理视图）→ 不过滤，向后兼容。"""
    writer_id = episodic.save("写作私有 阈值配置 蓝色优先", importance=5, agent_id=AGENT_WRITER)
    coder_id = episodic.save("编码私有 阈值配置 红色优先", importance=5, agent_id=AGENT_CODER)
    shared_id = episodic.save("共享偏好 阈值配置 绿色优先", importance=5)

    assert _ids(episodic.search(QUERY)) == {writer_id, coder_id, shared_id}
    assert _ids(episodic._search_like(QUERY)) == {writer_id, coder_id, shared_id}


def test_episodic_save_defaults_to_shared(db: Database, episodic: EpisodicMemory) -> None:
    memory_id = episodic.save("默认共享 阈值配置", importance=5)

    row = db.get_connection().execute(
        "SELECT agent_id FROM memories_episodic WHERE id = ?", (memory_id,)
    ).fetchone()
    assert row["agent_id"] is None


def test_episodic_get_recent_filtered_by_agent(episodic: EpisodicMemory) -> None:
    writer_id = episodic.save("写作私有 阈值配置", importance=5, agent_id=AGENT_WRITER)
    coder_id = episodic.save("编码私有 阈值配置", importance=5, agent_id=AGENT_CODER)
    shared_id = episodic.save("共享偏好 阈值配置", importance=5)

    assert _ids(episodic.get_recent(limit=50, agent_id=AGENT_WRITER)) == {
        writer_id,
        shared_id,
    }
    assert _ids(episodic.get_recent(limit=50)) == {writer_id, coder_id, shared_id}


# ---------- 语义记忆 ----------


def test_semantic_fts_private_isolated_and_shared_visible(semantic: SemanticMemory) -> None:
    writer_id = semantic.save("写作私有知识 阈值配置 蓝色优先", agent_id=AGENT_WRITER)
    coder_id = semantic.save("编码私有知识 阈值配置 红色优先", agent_id=AGENT_CODER)
    shared_id = semantic.save("共享用户知识 阈值配置 绿色优先")

    writer_visible = _ids(semantic.search(QUERY, agent_id=AGENT_WRITER))
    assert writer_visible == {writer_id, shared_id}
    coder_visible = _ids(semantic.search(QUERY, agent_id=AGENT_CODER))
    assert coder_visible == {coder_id, shared_id}


def test_semantic_like_path_private_isolated_and_shared_visible(
    semantic: SemanticMemory,
) -> None:
    writer_id = semantic.save("写作私有知识 阈值配置 蓝色优先", agent_id=AGENT_WRITER)
    coder_id = semantic.save("编码私有知识 阈值配置 红色优先", agent_id=AGENT_CODER)
    shared_id = semantic.save("共享用户知识 阈值配置 绿色优先")

    writer_visible = _ids(semantic._search_like(QUERY, agent_id=AGENT_WRITER))
    assert writer_visible == {writer_id, shared_id}
    coder_visible = _ids(semantic._search_like(QUERY, agent_id=AGENT_CODER))
    assert coder_visible == {coder_id, shared_id}


def test_semantic_save_defaults_to_shared(db: Database, semantic: SemanticMemory) -> None:
    memory_id = semantic.save("默认共享知识 阈值配置")

    row = db.get_connection().execute(
        "SELECT agent_id FROM memories_semantic WHERE id = ?", (memory_id,)
    ).fetchone()
    assert row["agent_id"] is None


def test_semantic_get_recent_filtered_by_agent(semantic: SemanticMemory) -> None:
    writer_id = semantic.save("写作私有知识 阈值配置", agent_id=AGENT_WRITER)
    coder_id = semantic.save("编码私有知识 阈值配置", agent_id=AGENT_CODER)
    shared_id = semantic.save("共享用户知识 阈值配置")

    assert _ids(semantic.get_recent(limit=50, agent_id=AGENT_WRITER)) == {
        writer_id,
        shared_id,
    }
    assert _ids(semantic.get_recent(limit=50)) == {writer_id, coder_id, shared_id}


# ---------- scope 模块可见性助手 ----------


def test_agent_visibility_sql_unfiltered_without_agent() -> None:
    assert memory_scope.agent_visibility_sql(None) == ("", [])
    assert memory_scope.agent_visibility_sql("") == ("", [])


def test_agent_visibility_sql_with_agent_and_prefix() -> None:
    sql, params = memory_scope.agent_visibility_sql(AGENT_WRITER, prefix="me.")
    assert "me.agent_id = ?" in sql
    assert "me.agent_id IS NULL" in sql
    assert params == [AGENT_WRITER]


def test_is_row_visible_agent_dimension() -> None:
    shared = {"agent_id": None, "scope": "user"}
    private = {"agent_id": AGENT_WRITER, "scope": "user"}
    other = {"agent_id": AGENT_CODER, "scope": "user"}

    assert memory_scope.is_row_visible(shared, None, AGENT_WRITER)
    assert memory_scope.is_row_visible(private, None, AGENT_WRITER)
    assert not memory_scope.is_row_visible(other, None, AGENT_WRITER)
    # 不传当前专家 → 不限制（历史调用 / 管理视图）
    assert memory_scope.is_row_visible(other, None)
