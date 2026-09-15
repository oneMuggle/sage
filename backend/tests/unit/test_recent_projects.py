"""Unit tests for backend.storage.recent_projects.

P8（2026-09-15）：存储迁移到 projects 注册表（SQLite）——本文件从
"JSON 文件读写"语义重写为"注册表投影"语义；旧 JSON 仅作为一次性迁移
来源（`_ensure_legacy_import`）覆盖保留。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.data.database import Database  # noqa: F401 — autouse 夹具已隔离库
from backend.storage.recent_projects import (
    MAX_RECENT,
    RecentProject,
    load_recent,
    most_recent_parent,
    record_recent,
    save_recent,
    user_data_dir,
)


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect user data dir to tmp_path (legacy JSON import source)."""
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    return tmp_path


# 1. 空库 → 空清单（无 legacy JSON 时迁移为 no-op）
def test_load_recent_returns_empty_when_registry_empty(isolated_data_dir: Path):
    assert load_recent() == []
    # 迁移探针不应创建 JSON（只在存在时导入并改名）
    assert not (isolated_data_dir / "recent-projects.json.migrated").exists()


# 2/3. legacy JSON：空文件 → no-op；损坏 → .bak 备份 + 空清单
def test_load_recent_legacy_empty_file_is_noop(isolated_data_dir: Path):
    (isolated_data_dir / "recent-projects.json").write_text("")
    assert load_recent() == []
    # 迁移完成即改名（空文件也不例外），避免每次读取重复探针
    assert (isolated_data_dir / "recent-projects.json.migrated").exists()


def test_load_recent_backs_up_corrupted_file(isolated_data_dir: Path):
    p = isolated_data_dir / "recent-projects.json"
    p.write_text("{ this is not valid json")
    result = load_recent()
    assert result == []
    bak_files = list(isolated_data_dir.glob("recent-projects.json.bak"))
    assert len(bak_files) == 1


# 4. legacy JSON 导入：有效条目入库、无效跳过、文件改名 .migrated
def test_load_recent_imports_legacy_json(isolated_data_dir: Path):
    p = isolated_data_dir / "recent-projects.json"
    p.write_text(
        json.dumps(
            [
                {"path": "/a", "name": "a", "opened_at": 1000.0, "intent": "create"},
                {"bogus": "entry"},
                {"path": "/b", "name": "b", "opened_at": 2000.0, "intent": "open"},
            ]
        )
    )
    items = load_recent()
    # opened_at 2000.0s 的 /b 更新 → 排最前；无效条目跳过
    assert [i.path for i in items] == ["/b", "/a"]
    assert items[0].intent == "open"
    assert items[1].intent == "create"
    assert items[1].opened_at == 1000.0
    # 一次性迁移：改名 + 不再重复导入
    assert (isolated_data_dir / "recent-projects.json.migrated").exists()
    assert load_recent() == items


# 5. save_recent：经注册表持久化（load_recent 回读一致）
def test_save_recent_roundtrips_through_registry(isolated_data_dir: Path):
    items = [RecentProject(path="/x", name="x", opened_at=1.0, intent="create")]
    save_recent(items)
    loaded = load_recent()
    assert len(loaded) == 1
    assert loaded[0].path == "/x"
    assert loaded[0].intent == "create"


# 6. record_recent: new entry -> length +1
def test_record_recent_appends_new_entry(isolated_data_dir: Path):
    record_recent("/a", "a", "create")
    items = load_recent()
    assert len(items) == 1
    assert items[0].path == "/a"
    assert items[0].name == "a"
    assert items[0].intent == "create"
    assert items[0].opened_at > 0


# 7. record_recent: duplicate path -> moves to head, length unchanged
def test_record_recent_dedup_moves_to_head(isolated_data_dir: Path):
    record_recent("/a", "a", "create")
    record_recent("/b", "b", "open")
    record_recent("/a", "a", "open")
    items = load_recent()
    assert len(items) == 2
    assert items[0].path == "/a"
    assert items[0].intent == "open"
    assert items[1].path == "/b"


# 8. MAX_RECENT 是读侧投影截断：注册表保留全部行，投影只回前 10 条
def test_record_recent_truncates_projection_to_max(isolated_data_dir: Path):
    for i in range(MAX_RECENT + 5):
        record_recent(f"/p{i}", f"p{i}", "create")
    items = load_recent()
    assert len(items) == MAX_RECENT
    # Most recent should be at the head
    assert items[0].path == f"/p{MAX_RECENT + 4}"

    # 注册表本身保留全部行（越窗行仍归属侧栏清单，不被删除）
    from backend.data.database import get_database

    total = get_database().get_connection().execute(
        "SELECT COUNT(*) AS c FROM projects"
    ).fetchone()["c"]
    assert total == MAX_RECENT + 5


def test_record_recent_rejects_invalid_intent(isolated_data_dir: Path):
    with pytest.raises(ValueError, match="create.*open"):
        record_recent("/invalid", "invalid", "delete")  # type: ignore[arg-type]


# 9. most_recent_parent: empty list -> None
def test_most_recent_parent_returns_none_when_empty(isolated_data_dir: Path):
    assert most_recent_parent() is None


# 10. most_recent_parent: non-empty -> parent of first item
def test_most_recent_parent_returns_parent_of_head(isolated_data_dir: Path, tmp_path: Path):
    target = tmp_path / "my-wiki"
    record_recent(str(target), "my-wiki", "create")
    parent = most_recent_parent()
    assert parent is not None
    assert Path(parent).resolve() == tmp_path.resolve()


# 11. most_recent_parent: parent deleted -> None (graceful)
def test_most_recent_parent_returns_none_when_parent_missing(
    isolated_data_dir: Path, tmp_path: Path
):
    ghost = tmp_path / "does-not-exist" / "wiki"
    record_recent(str(ghost), "wiki", "create")
    assert most_recent_parent() is None


# 12. user_data_dir: env var priority（legacy 迁移来源路径仍遵循）
def test_user_data_dir_uses_env_var_when_set(isolated_data_dir: Path, tmp_path: Path):
    assert user_data_dir() == isolated_data_dir


# 13. save_recent 越窗保护：只删上一窗口内且不在新清单的行
def test_save_recent_deletes_only_within_previous_window(isolated_data_dir: Path):
    record_recent("/a", "a", "create")
    record_recent("/b", "b", "create")
    record_recent("/c", "c", "create")
    # 上一窗口 = {a, b, c}；新清单只留 c → a/b 从注册表删除
    save_recent([RecentProject(path="/c", name="c", opened_at=1.0, intent="open")])
    assert [i.path for i in load_recent()] == ["/c"]

    # save_recent = "这就是完整 recents 清单"（窗口重写语义）：
    # d 经 record_recent 已进入窗口，随后的 save([c]) 会移除它
    record_recent("/d", "d", "open")
    save_recent([RecentProject(path="/c", name="c", opened_at=1.0, intent="open")])
    assert [i.path for i in load_recent()] == ["/c"]


# 14. save_recent / record_recent 支持 pydantic v1 属性形态（鸭子类型）
def test_save_recent_supports_pydantic_v1_api(isolated_data_dir: Path):
    class V1Project:
        path = "/v1"
        name = "v1"
        opened_at = 1.0
        intent = "open"

    save_recent([V1Project()])

    loaded = load_recent()
    assert len(loaded) == 1
    assert loaded[0].path == "/v1"


def test_save_recent_does_not_swallow_serialization_errors(isolated_data_dir: Path):
    class BrokenProject:
        path = "/broken"

    with pytest.raises(OSError, match="recent projects"):
        save_recent([BrokenProject()])
