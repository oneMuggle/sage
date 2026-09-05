"""工作区检查点工具单元测试（对标增强 Phase-1 T2）。

快照存 ``SAGE_USER_DATA_DIR``（测试里 monkeypatch 到 tmp），全部用
tmp_path 工作区 —— 跨平台、无子进程、Windows/CI 全绿。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools import checkpoint_tool
from backend.tools.checkpoint_tool import (
    CheckpointCreateTool,
    CheckpointListTool,
    CheckpointRestoreTool,
    _checkpoint_dir,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def user_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "userdata"
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(data))
    return data


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("print('v1')\n", encoding="utf-8")
    (ws / "docs").mkdir()
    (ws / "docs" / "note.md").write_text("# note\n", encoding="utf-8")
    return ws


def _tool(tool_cls, ws: Path):
    return tool_cls(policy=ToolPolicy(workspace_root=str(ws)))


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_writes_snapshot_and_reports(user_data, workspace):
    result = _tool(CheckpointCreateTool, workspace).execute()
    assert result.success is True
    assert result.content["files"] == 2
    assert result.content["skipped"] == []
    assert result.content["bytes"] > 0

    zips = list(_checkpoint_dir(workspace).glob("*.zip"))
    assert len(zips) == 1
    assert zips[0].stem == result.content["checkpoint_id"]


def test_create_excludes_heavy_dirs_and_large_files(user_data, workspace):
    (workspace / ".git").mkdir()
    (workspace / ".git" / "HEAD").write_text("git\n", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "pkg.js").write_text("js\n", encoding="utf-8")
    big = workspace / "big.bin"
    big.write_bytes(b"x" * (checkpoint_tool.MAX_FILE_BYTES + 1))

    result = _tool(CheckpointCreateTool, workspace).execute()
    assert result.success is True
    assert result.content["files"] == 2  # app.py + docs/note.md
    assert result.content["skipped"] == ["big.bin"]

    with zipfile.ZipFile(next(_checkpoint_dir(workspace).glob("*.zip"))) as archive:
        names = archive.namelist()
    assert ".git/HEAD" not in names
    assert "node_modules/pkg.js" not in names
    assert "app.py" in names


def test_create_aborts_when_total_size_over_cap(user_data, workspace, monkeypatch):
    monkeypatch.setattr(checkpoint_tool, "MAX_TOTAL_BYTES", 10)
    result = _tool(CheckpointCreateTool, workspace).execute()
    assert result.success is False
    assert "256MiB" in (result.error or "") or "上限" in (result.error or "")
    assert list(_checkpoint_dir(workspace).glob("*.zip")) == []
    assert not list(_checkpoint_dir(workspace).glob("*.tmp"))


def test_create_requires_bound_workspace():
    result = CheckpointCreateTool(policy=ToolPolicy()).execute()
    assert result.success is False
    assert "绑定工作区" in (result.error or "")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_returns_snapshots_newest_first(user_data, workspace):
    first = _tool(CheckpointCreateTool, workspace).execute()
    second = _tool(CheckpointCreateTool, workspace).execute()
    result = _tool(CheckpointListTool, workspace).execute()
    assert result.success is True
    ids = [c["checkpoint_id"] for c in result.content["checkpoints"]]
    assert ids == [second.content["checkpoint_id"], first.content["checkpoint_id"]]
    assert all(c["files"] == 2 for c in result.content["checkpoints"])


def test_list_empty_when_no_snapshots(user_data, workspace):
    result = _tool(CheckpointListTool, workspace).execute()
    assert result.success is True
    assert result.content["checkpoints"] == []


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def test_restore_reverts_modified_files(user_data, workspace):
    checkpoint_id = _tool(CheckpointCreateTool, workspace).execute().content["checkpoint_id"]

    (workspace / "app.py").write_text("print('v2 broken')\n", encoding="utf-8")
    (workspace / "docs" / "note.md").write_text("# overwritten\n", encoding="utf-8")

    result = _tool(CheckpointRestoreTool, workspace).execute(checkpoint_id=checkpoint_id)
    assert result.success is True
    assert result.content["restored"] == 2
    assert (workspace / "app.py").read_text(encoding="utf-8") == "print('v1')\n"
    assert (workspace / "docs" / "note.md").read_text(encoding="utf-8") == "# note\n"


def test_restore_keeps_files_created_after_snapshot(user_data, workspace):
    checkpoint_id = _tool(CheckpointCreateTool, workspace).execute().content["checkpoint_id"]
    (workspace / "later.txt").write_text("new file\n", encoding="utf-8")

    result = _tool(CheckpointRestoreTool, workspace).execute(checkpoint_id=checkpoint_id)
    assert result.success is True
    assert (workspace / "later.txt").read_text(encoding="utf-8") == "new file\n"


def test_restore_rejects_zip_slip(user_data, workspace):
    _tool(CheckpointCreateTool, workspace).execute()
    # 伪造带越界成员的 zip，冒充合法快照
    malicious_id = "20260101-000000-abcdef"
    evil_zip = _checkpoint_dir(workspace) / f"{malicious_id}.zip"
    with zipfile.ZipFile(evil_zip, "w") as archive:
        archive.writestr("../evil.txt", "pwned")

    result = _tool(CheckpointRestoreTool, workspace).execute(checkpoint_id=malicious_id)
    assert result.success is False
    assert "越界" in (result.error or "")
    assert not (workspace.parent / "evil.txt").exists()
    evil_zip.unlink()


def test_restore_validates_id_and_existence(user_data, workspace):
    tool = _tool(CheckpointRestoreTool, workspace)
    assert tool.execute(checkpoint_id="../escape").success is False
    assert tool.execute(checkpoint_id="").success is False
    assert tool.execute(checkpoint_id="20990101-000000-deadbeef").success is False
    assert tool.execute(checkpoint_id="x", extra=1).success is False


# ---------------------------------------------------------------------------
# retention（保留策略）
# ---------------------------------------------------------------------------


def test_retention_drops_oldest_beyond_limit(user_data, workspace, monkeypatch):
    monkeypatch.setattr(checkpoint_tool, "RETENTION_COUNT", 2)
    ids = []
    for round_index in range(3):
        (workspace / "app.py").write_text(f"print('v{round_index}')\n", encoding="utf-8")
        ids.append(_tool(CheckpointCreateTool, workspace).execute().content["checkpoint_id"])

    remaining = {p.stem for p in _checkpoint_dir(workspace).glob("*.zip")}
    assert remaining == set(ids[1:])
