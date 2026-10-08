"""R185 — AgentProfile 持久层单元测试（`backend/data/agent_repo.py`）。

真实临时库（conftest autouse `setup_test_db`），不 mock SQL。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.data.agent_repo import AgentRepository

pytestmark = pytest.mark.unit


def _profile(agent_id: str = "coder", **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "id": agent_id,
        "name": "Coder",
        "role": "编码助手",
        "system_prompt": "你是编码助手",
        "tools": ["bash", "read_file"],
        "memory_access": ["sessions"],
        "model_config": {"model": "m1", "temperature": 0.2},
        "max_iterations": 12,
        "enabled": True,
        "description": "默认编码代理",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def repo() -> AgentRepository:
    return AgentRepository()


# ---------------------------------------------------------------------------
# 读（agents 表由 init_db 预置种子，非空起点）
# ---------------------------------------------------------------------------


def test_seeded_table_reads(repo: AgentRepository) -> None:
    rows = repo.list_all()
    assert rows  # init_db 预置了默认 agent
    assert repo.count() == len(rows)
    assert all(r["id"] and isinstance(r["enabled"], bool) for r in rows)
    assert repo.get("ghost-id") is None


def test_upsert_and_get_roundtrip(repo: AgentRepository) -> None:
    repo.upsert(_profile())
    loaded = repo.get("coder")
    assert loaded is not None
    assert loaded["name"] == "Coder"
    assert loaded["tools"] == ["bash", "read_file"]
    assert loaded["memory_access"] == ["sessions"]
    assert loaded["model_config"] == {"model": "m1", "temperature": 0.2}
    assert loaded["max_iterations"] == 12
    assert loaded["enabled"] is True
    assert loaded["updated_at"] > 0


def test_upsert_defaults_for_sparse_profile(repo: AgentRepository) -> None:
    repo.upsert({"id": "minimal", "name": "M", "role": "r"})
    loaded = repo.get("minimal")
    assert loaded is not None
    assert loaded["system_prompt"] == ""
    assert loaded["tools"] == []
    assert loaded["model_config"] == {}
    assert loaded["max_iterations"] == 10
    assert loaded["enabled"] is True


def test_upsert_replaces_and_orders_by_id(repo: AgentRepository) -> None:
    baseline = repo.count()
    repo.upsert(_profile("z-b"))
    repo.upsert(_profile("z-a"))
    repo.upsert(_profile("z-b", name="Coder-2"))
    rows = [r for r in repo.list_all() if r["id"].startswith("z-")]
    assert [r["id"] for r in rows] == ["z-a", "z-b"]
    assert rows[1]["name"] == "Coder-2"
    assert repo.count() == baseline + 2  # 同 id REPLACE 不增行


def test_set_enabled(repo: AgentRepository) -> None:
    repo.upsert(_profile())
    assert repo.set_enabled("coder", False) is True
    assert repo.get("coder")["enabled"] is False
    assert repo.set_enabled("ghost", True) is False


# ---------------------------------------------------------------------------
# update（部分字段）
# ---------------------------------------------------------------------------


def test_update_partial_fields(repo: AgentRepository) -> None:
    repo.upsert(_profile())
    assert repo.update("coder", {"max_iterations": 30, "tools": ["web_search"]}) is True
    loaded = repo.get("coder")
    assert loaded is not None
    assert loaded["max_iterations"] == 30
    assert loaded["tools"] == ["web_search"]
    assert loaded["name"] == "Coder"  # 未传字段不变
    assert loaded["model_config"] == {"model": "m1", "temperature": 0.2}


def test_update_serializes_json_and_bool(repo: AgentRepository) -> None:
    repo.upsert(_profile())
    repo.update("coder", {"enabled": False, "model_config": {"model": "m2"}})
    loaded = repo.get("coder")
    assert loaded is not None
    assert loaded["enabled"] is False
    assert loaded["model_config"] == {"model": "m2"}


def test_update_empty_profile_is_existence_check(repo: AgentRepository) -> None:
    repo.upsert(_profile())
    assert repo.update("coder", {}) is True
    assert repo.update("ghost", {}) is False


def test_update_missing_agent_returns_false(repo: AgentRepository) -> None:
    assert repo.update("ghost", {"name": "x"}) is False


def test_updated_at_bumps_on_update(repo: AgentRepository) -> None:
    repo.upsert(_profile())
    before = repo.get("coder")["updated_at"]
    repo.update("coder", {"name": "Coder-3"})
    after = repo.get("coder")["updated_at"]
    assert after >= before


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------


def test_seed_defaults_if_empty(repo: AgentRepository) -> None:
    # 表已有 init_db 预置种子 → 非空直接跳过
    assert repo.seed_defaults_if_empty() == 0

    # 清空后种子路径生效，且重复调用幂等
    conn = repo.db.get_connection()
    conn.execute("DELETE FROM agents")
    conn.commit()
    assert repo.count() == 0
    inserted = repo.seed_defaults_if_empty()
    assert inserted == repo.count()
    assert inserted > 0
    assert repo.seed_defaults_if_empty() == 0
