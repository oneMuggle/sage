"""A4 decision 路由 — API tests.

POST /api/v1/orchestration/lanes/{id}/decision：
- 404 / 409（非 succeeded）/ 无 worktree 纯归档；
- worktree 合并成功 / 主仓脏拒绝 / 冲突回滚 / 丢失降级；
- reject 清理 + 幂等。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from backend.data.orchestration_repo import LaneEventRepository
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.task_registry import TaskRegistry


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True,
        text=True, timeout=60, check=True,
    )


def _main_repo(tmp_path: Path, name: str = "main") -> Path:
    d = tmp_path / name
    d.mkdir()
    _git("init", cwd=d)
    _git("config", "user.email", "t@t", cwd=d)
    _git("config", "user.name", "t", cwd=d)
    (d / "a.txt").write_text("v1\n", encoding="utf-8")
    _git("add", ".", cwd=d)
    _git("commit", "-m", "init", cwd=d)
    return d


def _make_wt(main: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "--detach", str(dest), "HEAD", cwd=main)
    return dest


def _seed_lane(worktree=None, status: str = "succeeded"):
    task = TaskRegistry().create_task(
        name="t1", description="d", task_type="general"
    )
    reg = LaneRegistry()
    # worktree 必须在 create 时传入——LaneRepository.update 不落 worktree 列
    # （与 dispatcher 建 lane 时预置 worktree 的生产路径一致）。
    lane = reg.create_lane(
        task_id=task.task_id,
        worktree=str(worktree) if worktree is not None else None,
    )
    if status == "succeeded":
        lane.mark_ready()
        lane.mark_running()
        lane.mark_succeeded()
    elif status == "running":
        lane.mark_ready()
        lane.mark_running()
    reg.update_lane(lane)
    return lane


def _events_for(lane_id: str):
    return LaneEventRepository().list_by_lane(lane_id)


class TestDecisionRoute:
    async def test_unknown_lane_404(self, client):
        resp = await client.post(
            "/api/v1/orchestration/lanes/lane-nope/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 404

    async def test_accept_non_succeeded_409(self, client):
        lane = _seed_lane(status="running")
        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane.lane_id}/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 409

    async def test_reject_non_succeeded_409(self, client):
        lane = _seed_lane(status="running")
        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane.lane_id}/decision",
            json={"decision": "reject"},
        )
        assert resp.status_code == 409

    async def test_accept_without_worktree_archives(self, client):
        lane = _seed_lane()
        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane.lane_id}/decision",
            json={"decision": "accept", "reason": "looks good"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["merged"] is False
        assert body["already"] is False
        events = _events_for(lane.lane_id)
        assert any(e["event_type"] == "lane.accepted" for e in events)

    async def test_accept_merges_worktree(self, client, tmp_path):
        main = _main_repo(tmp_path)
        wt = _make_wt(main, tmp_path / "wt")
        (wt / "a.txt").write_text("v2\n", encoding="utf-8")
        lane = _seed_lane(worktree=wt)
        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane.lane_id}/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] is True
        assert body["merge"]["code"] == "merged"
        assert (main / "a.txt").read_text(encoding="utf-8") == "v2\n"
        assert not wt.exists()  # 合后清理
        events = _events_for(lane.lane_id)
        assert any(e["event_type"] == "lane.accepted" for e in events)

    async def test_accept_main_dirty_409_keeps_worktree(self, client, tmp_path):
        main = _main_repo(tmp_path)
        wt = _make_wt(main, tmp_path / "wt")
        (wt / "a.txt").write_text("v2\n", encoding="utf-8")
        (main / "a.txt").write_text("dirty\n", encoding="utf-8")
        lane = _seed_lane(worktree=wt)
        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane.lane_id}/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 409
        assert wt.exists()  # 拒绝后 worktree 保留，可重试

    async def test_accept_conflicts_409_lists_files(self, client, tmp_path):
        main = _main_repo(tmp_path)
        wt = _make_wt(main, tmp_path / "wt")
        (main / "a.txt").write_text("main\n", encoding="utf-8")
        _git("add", ".", cwd=main)
        _git("commit", "-m", "main", cwd=main)
        (wt / "a.txt").write_text("wt\n", encoding="utf-8")
        lane = _seed_lane(worktree=wt)
        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane.lane_id}/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 409
        assert "a.txt" in resp.json()["detail"]
        assert wt.exists()

    async def test_accept_missing_worktree_degrades(self, client, tmp_path):
        lane = _seed_lane(worktree=tmp_path / "gone")
        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane.lane_id}/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] is False
        assert body["warning"]  # 降级但明示

    async def test_accept_idempotent(self, client):
        lane = _seed_lane()
        url = f"/api/v1/orchestration/lanes/{lane.lane_id}/decision"
        assert (await client.post(url, json={"decision": "accept"})).status_code == 200
        second = await client.post(url, json={"decision": "accept"})
        assert second.json()["already"] is True

    async def test_reject_removes_worktree(self, client, tmp_path):
        main = _main_repo(tmp_path)
        wt = _make_wt(main, tmp_path / "wt")
        (wt / "a.txt").write_text("v2\n", encoding="utf-8")
        lane = _seed_lane(worktree=wt)
        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane.lane_id}/decision",
            json={"decision": "reject", "reason": "不对，重做"},
        )
        assert resp.status_code == 200
        assert resp.json()["merged"] is False
        assert not wt.exists()
        assert (main / "a.txt").read_text(encoding="utf-8") == "v1\n"  # 主仓未动
        events = _events_for(lane.lane_id)
        assert any(e["event_type"] == "lane.rejected" for e in events)

    async def test_reject_idempotent(self, client):
        lane = _seed_lane()
        url = f"/api/v1/orchestration/lanes/{lane.lane_id}/decision"
        assert (await client.post(url, json={"decision": "reject"})).status_code == 200
        second = await client.post(url, json={"decision": "reject"})
        assert second.json()["already"] is True
