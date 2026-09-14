"""A4 worktree_merge — unit tests (real git repos in tmp)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.orchestration.worktree_merge import (
    accept_lane_worktree,
    find_main_repo,
    sanitize_branch_suffix,
)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True,
        text=True, timeout=60, check=True,
    )


@pytest.fixture()
def main_repo(tmp_path: Path) -> Path:
    d = tmp_path / "main"
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


def _porcelain(repo: Path) -> str:
    return _git("status", "--porcelain", cwd=repo).stdout.strip()


class TestFindMain:
    def test_resolves_main_repo(self, main_repo, tmp_path):
        wt = _make_wt(main_repo, tmp_path / "wt")
        assert find_main_repo(wt) == main_repo

    def test_plain_dir_is_none(self, tmp_path):
        assert find_main_repo(tmp_path) is None


class TestAccept:
    def test_no_changes_is_ok(self, main_repo, tmp_path):
        wt = _make_wt(main_repo, tmp_path / "wt")
        r = accept_lane_worktree(str(wt), lane_id="lane-t1")
        assert r.ok is True
        assert r.code == "no-changes"

    def test_happy_path_merges(self, main_repo, tmp_path):
        wt = _make_wt(main_repo, tmp_path / "wt")
        (wt / "a.txt").write_text("v2\n", encoding="utf-8")
        (wt / "new.txt").write_text("new\n", encoding="utf-8")
        r = accept_lane_worktree(str(wt), lane_id="lane-t1")
        assert r.ok is True
        assert r.code == "merged"
        assert (main_repo / "a.txt").read_text(encoding="utf-8") == "v2\n"
        assert (main_repo / "new.txt").exists()
        assert "a.txt" in r.files_changed
        assert r.branch.startswith("lane/accept/lane-t1-")
        # 分支保留备审计；merge commit 存在
        branches = _git("branch", "--list", "lane/accept/*", cwd=main_repo).stdout
        assert r.branch in branches
        merges = _git("log", "--merges", "--oneline", cwd=main_repo).stdout
        assert merges.strip() != ""

    def test_main_dirty_refused(self, main_repo, tmp_path):
        wt = _make_wt(main_repo, tmp_path / "wt")
        (wt / "a.txt").write_text("v2\n", encoding="utf-8")
        (main_repo / "a.txt").write_text("dirty\n", encoding="utf-8")
        r = accept_lane_worktree(str(wt), lane_id="lane-t1")
        assert r.ok is False
        assert r.code == "main-dirty"
        # 双方不动
        assert (main_repo / "a.txt").read_text(encoding="utf-8") == "dirty\n"
        assert (wt / "a.txt").read_text(encoding="utf-8") == "v2\n"

    def test_conflicts_abort_cleanly(self, main_repo, tmp_path):
        wt = _make_wt(main_repo, tmp_path / "wt")
        (main_repo / "a.txt").write_text("main\n", encoding="utf-8")
        _git("add", ".", cwd=main_repo)
        _git("commit", "-m", "main", cwd=main_repo)
        (wt / "a.txt").write_text("wt\n", encoding="utf-8")
        r = accept_lane_worktree(str(wt), lane_id="lane-t1")
        assert r.ok is False
        assert r.code == "conflicts"
        assert r.conflict_files == ["a.txt"]
        # 主仓回滚干净，无 MERGE_HEAD
        assert _porcelain(main_repo) == ""
        verify = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
            cwd=str(main_repo),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert verify.returncode != 0

    def test_missing_worktree(self, tmp_path):
        r = accept_lane_worktree(str(tmp_path / "nope"), lane_id="lane-t1")
        assert r.ok is False
        assert r.code == "worktree-missing"

    def test_not_a_repo(self, tmp_path):
        r = accept_lane_worktree(str(tmp_path), lane_id="lane-t1")
        assert r.ok is False
        assert r.code == "not-a-repo"

    def test_self_merge_refused(self, main_repo):
        r = accept_lane_worktree(str(main_repo), lane_id="lane-t1")
        assert r.ok is False
        assert r.code == "not-a-worktree"

    def test_missing_identity_falls_back(self, main_repo, tmp_path):
        _git("config", "user.email", "", cwd=main_repo)
        wt = _make_wt(main_repo, tmp_path / "wt")
        (wt / "a.txt").write_text("v2\n", encoding="utf-8")
        r = accept_lane_worktree(str(wt), lane_id="lane-t1")
        assert r.ok is True
        assert r.code == "merged"


class TestSanitize:
    def test_safe_passthrough(self):
        assert sanitize_branch_suffix("lane-t1") == "lane-t1"

    def test_unsafe_replaced(self):
        assert sanitize_branch_suffix("a b~c") == "a-b-c"

    def test_empty_fallback(self):
        assert sanitize_branch_suffix("~~~") == "lane"
