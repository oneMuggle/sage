# ruff: noqa: UP006, UP007 — release/win7 Python 3.8 兼容
"""M4-T3 — ``AgentVersionRepository`` 单元测试（真实临时库，不 mock SQL）。

覆盖：
- snapshot 写入 + 版本号返回
- snapshot 拒绝缺失/非法 version
- list_versions 倒序
- read_version 不存在返回 None
- latest_version
- prune 50-version 裁剪（用更小的 cap 验证）
- diff 字段级比对（白名单内变化、白名单外忽略、JSON 结构对比）
- delete_all_for_agent 级联删除
- INSERT OR REPLACE 语义：同 (agent_id, version) 再次 snapshot 覆盖
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.data.agent_version_repo import (
    DIFF_FIELD_WHITELIST,
    AgentVersionRepository,
)

pytestmark = pytest.mark.unit


def _profile(
    agent_id: str = "a1",
    version: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "id": agent_id,
        "name": "Expert-A",
        "role": "specialist",
        "system_prompt": "你是 A",
        "tools": ["bash"],
        "memory_access": ["user"],
        "model_config": {"model": "m1", "temperature": 0.5},
        "max_iterations": 20,
        "enabled": True,
        "description": "desc",
        "version": version,
        "source": "user",
        "permission_mode": "workspace_write",
        "skills": ["writing"],
        "knowledge_bindings": [],
        "memory_policy": {"write_scope": "specialist"},
        "persona_ui": {"avatar": "🤖", "tagline": "A tagline"},
        "updated_at": 99999,  # 白名单外字段；diff 应忽略
    }
    base.update(overrides)
    return base


@pytest.fixture()
def repo() -> AgentVersionRepository:
    return AgentVersionRepository()


# ---------------------------------------------------------------------------
# 写 / 拒绝非法输入
# ---------------------------------------------------------------------------


def test_snapshot_writes_and_returns_version(repo: AgentVersionRepository) -> None:
    written = repo.snapshot("a1", _profile("a1", version=1), reason="create")
    assert written == 1
    versions = repo.list_versions("a1")
    assert [v["version"] for v in versions] == [1]
    assert versions[0]["reason"] == "create"
    assert versions[0]["created_at"] > 0


def test_snapshot_rejects_missing_version(repo: AgentVersionRepository) -> None:
    with pytest.raises(ValueError, match="profile.version"):
        repo.snapshot("a1", {"id": "a1", "name": "X"})  # 无 version
    with pytest.raises(ValueError, match="profile.version"):
        repo.snapshot("a1", {"id": "a1", "version": 0})
    with pytest.raises(ValueError, match="profile.version"):
        repo.snapshot("a1", {"id": "a1", "version": -1})


def test_snapshot_replaces_same_version(repo: AgentVersionRepository) -> None:
    repo.snapshot("a1", _profile("a1", version=3, name="v3a"), reason="update")
    repo.snapshot("a1", _profile("a1", version=3, name="v3b"), reason="rollback")
    # INSERT OR REPLACE 语义：同 version 覆盖
    loaded = repo.read_version("a1", 3)
    assert loaded is not None
    assert loaded["name"] == "v3b"
    versions = repo.list_versions("a1")
    assert len(versions) == 1
    assert versions[0]["reason"] == "rollback"


def test_snapshot_overwrite_false_keeps_existing(repo: AgentVersionRepository) -> None:
    """``overwrite=False``（PATCH 回填钩子）：已存在的版本保留原始行。"""
    repo.snapshot("a1", _profile("a1", version=1, name="original"), reason="create")
    repo.snapshot(
        "a1", _profile("a1", version=1, name="clobber"), reason="update", overwrite=False
    )
    loaded = repo.read_version("a1", 1)
    assert loaded is not None
    assert loaded["name"] == "original"
    versions = repo.list_versions("a1")
    assert len(versions) == 1
    assert versions[0]["reason"] == "create"
    # 版本缺失时 overwrite=False 仍正常写入
    repo.snapshot("a1", _profile("a1", version=2), reason="update", overwrite=False)
    assert repo.latest_version("a1") == 2


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------


def test_list_versions_descending(repo: AgentVersionRepository) -> None:
    for v in (1, 3, 5, 2, 4):
        repo.snapshot("a1", _profile("a1", version=v), reason="update")
    versions = repo.list_versions("a1")
    assert [v["version"] for v in versions] == [5, 4, 3, 2, 1]


def test_list_versions_empty_when_no_snapshots(repo: AgentVersionRepository) -> None:
    assert repo.list_versions("ghost") == []


def test_read_version_returns_none_when_missing(repo: AgentVersionRepository) -> None:
    assert repo.read_version("ghost", 1) is None
    repo.snapshot("a1", _profile("a1", version=1))
    assert repo.read_version("a1", 99) is None


def test_read_version_round_trip_preserves_json(repo: AgentVersionRepository) -> None:
    profile = _profile(
        "a1",
        version=2,
        tools=["bash", "read_file"],
        model_config={"model": "m2", "temperature": 0.3},
        knowledge_bindings=[{"key": "kb1", "source": "specialist_private"}],
    )
    repo.snapshot("a1", profile, reason="update")
    loaded = repo.read_version("a1", 2)
    assert loaded is not None
    assert loaded["tools"] == ["bash", "read_file"]
    assert loaded["model_config"] == {"model": "m2", "temperature": 0.3}
    assert loaded["knowledge_bindings"] == [
        {"key": "kb1", "source": "specialist_private"}
    ]


def test_latest_version(repo: AgentVersionRepository) -> None:
    assert repo.latest_version("a1") is None
    repo.snapshot("a1", _profile("a1", version=4))
    repo.snapshot("a1", _profile("a1", version=2))
    repo.snapshot("a1", _profile("a1", version=7))
    assert repo.latest_version("a1") == 7


# ---------------------------------------------------------------------------
# 保留策略
# ---------------------------------------------------------------------------


def test_prune_keeps_latest_cap(repo: AgentVersionRepository) -> None:
    for v in range(1, 8):  # 写入 1..7
        repo.snapshot("a1", _profile("a1", version=v), cap=3)
    versions = repo.list_versions("a1")
    assert [v["version"] for v in versions] == [7, 6, 5]
    # 旧版本已被裁剪
    for v in (1, 2, 3, 4):
        assert repo.read_version("a1", v) is None


def test_prune_noop_when_under_cap(repo: AgentVersionRepository) -> None:
    for v in (1, 2, 3):
        repo.snapshot("a1", _profile("a1", version=v), cap=10)
    assert repo.prune("a1", cap=10) == 0
    assert len(repo.list_versions("a1")) == 3


def test_prune_rejects_nonpositive_cap(repo: AgentVersionRepository) -> None:
    with pytest.raises(ValueError, match="cap"):
        repo.prune("a1", cap=0)
    with pytest.raises(ValueError, match="cap"):
        repo.prune("a1", cap=-5)


def test_default_cap_is_50(repo: AgentVersionRepository) -> None:
    """默认 cap=50；写入 55 个版本应裁剪到 50。"""
    for v in range(1, 56):
        repo.snapshot("a1", _profile("a1", version=v))
    versions = repo.list_versions("a1")
    assert len(versions) == 50
    # 保留最大 5 个 + 从 6 开始保留 45 个 → 最小保留 6
    assert versions[-1]["version"] == 6
    assert versions[0]["version"] == 55


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def test_diff_detects_field_changes(repo: AgentVersionRepository) -> None:
    repo.snapshot(
        "a1",
        _profile("a1", version=1, name="OldName", system_prompt="old prompt"),
    )
    repo.snapshot(
        "a1",
        _profile("a1", version=2, name="NewName", system_prompt="new prompt"),
    )
    changes = repo.diff("a1", 1, 2)
    fields = {c["field"] for c in changes}
    assert "name" in fields
    assert "system_prompt" in fields
    name_change = next(c for c in changes if c["field"] == "name")
    assert name_change["before"] == "OldName"
    assert name_change["after"] == "NewName"


def test_diff_ignores_whitelist_excluded_fields(repo: AgentVersionRepository) -> None:
    """updated_at 不在白名单；改动应被忽略。"""
    repo.snapshot("a1", _profile("a1", version=1, updated_at=100))
    repo.snapshot("a1", _profile("a1", version=2, updated_at=999))
    changes = repo.diff("a1", 1, 2)
    # 除 version（必然变）外无其他字段变化
    fields = {c["field"] for c in changes}
    assert "updated_at" not in fields


def test_diff_detects_json_structure_changes(repo: AgentVersionRepository) -> None:
    repo.snapshot(
        "a1",
        _profile("a1", version=1, tools=["bash", "read_file"]),
    )
    repo.snapshot(
        "a1",
        _profile("a1", version=2, tools=["bash"]),
    )
    changes = repo.diff("a1", 1, 2)
    tools_change = next(c for c in changes if c["field"] == "tools")
    assert tools_change["before"] == ["bash", "read_file"]
    assert tools_change["after"] == ["bash"]


def test_diff_returns_empty_when_no_changes(repo: AgentVersionRepository) -> None:
    profile = _profile("a1", version=1)
    repo.snapshot("a1", profile)
    # 同 (agent_id, version=1) 的 INSERT OR REPLACE 覆盖，内容相同
    repo.snapshot("a1", profile)
    # 同 version 自己与自己 diff 无变化
    changes = repo.diff("a1", 1, 1)
    assert changes == []


def test_diff_raises_when_version_missing(
    repo: AgentVersionRepository,
) -> None:
    repo.snapshot("a1", _profile("a1", version=1))
    with pytest.raises(ValueError, match="不存在"):
        repo.diff("a1", 1, 99)
    with pytest.raises(ValueError, match="不存在"):
        repo.diff("a1", 99, 1)


def test_diff_whitelist_does_not_drift() -> None:
    """白名单字段应显式、稳定；任何新增需审慎考虑。"""
    expected = {
        "name",
        "role",
        "system_prompt",
        "description",
        "permission_mode",
        "source",
        "max_iterations",
        "enabled",
        "version",
        "tools",
        "memory_access",
        "skills",
        "knowledge_bindings",
        "memory_policy",
        "persona_ui",
        "model_config",
    }
    assert set(DIFF_FIELD_WHITELIST) == expected


# ---------------------------------------------------------------------------
# 级联删除
# ---------------------------------------------------------------------------


def test_delete_all_for_agent(repo: AgentVersionRepository) -> None:
    for v in (1, 2, 3):
        repo.snapshot("a1", _profile("a1", version=v))
    repo.snapshot("a2", _profile("a2", version=1))
    deleted = repo.delete_all_for_agent("a1")
    assert deleted == 3
    assert repo.list_versions("a1") == []
    # 另一个专家不受影响
    assert len(repo.list_versions("a2")) == 1


def test_delete_all_for_agent_returns_zero_when_empty(
    repo: AgentVersionRepository,
) -> None:
    assert repo.delete_all_for_agent("ghost") == 0
