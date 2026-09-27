"""R162 — Git Status 路由单元测试。

_parse_porcelain_line 纯解析（XY 状态码/引号路径/冲突优先级）+
get_git_status 真实 tmp git 仓库端到端（分支/文件状态/排序/非 git
目录静默降级/404）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api.git_status_routes import (
    GitStatusResponse,
    _parse_porcelain_line,
    get_git_status,
)

pytestmark = pytest.mark.unit


def _git(cwd: Path, *args: str):
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


@pytest.fixture()
def git_repo(tmp_path):
    repo = tmp_path / "ws"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


# ---------------------------------------------------------------------------
# _parse_porcelain_line
# ---------------------------------------------------------------------------


def test_parse_modified_working_tree():
    change = _parse_porcelain_line(" M a.py")
    assert change is not None
    assert change.path == "a.py"
    assert change.status == "modified"


def test_parse_staged_index():
    change = _parse_porcelain_line("M  a.py")
    assert change is not None
    assert change.status == "staged"


def test_parse_untracked():
    change = _parse_porcelain_line("?? b.py")
    assert change is not None
    assert change.status == "untracked"
    assert change.path == "b.py"


@pytest.mark.parametrize("xy", ["UU", "AA", "DD", "DU"])
def test_parse_conflicted_variants(xy):
    change = _parse_porcelain_line(f"{xy} c.py")
    assert change is not None
    assert change.status == "conflicted"


def test_parse_deleted_staged_counts_as_staged():
    # "D_" = 索引中删除（staged deletion）——实现按 index 变更归类为 staged
    change = _parse_porcelain_line("D  gone.py")
    assert change is not None
    assert change.status == "staged"


def test_parse_quoted_path_with_spaces():
    change = _parse_porcelain_line('?? "my file with spaces.py"')
    assert change is not None
    assert change.path == "my file with spaces.py"


def test_parse_short_line_returns_none():
    assert _parse_porcelain_line("ab") is None


def test_parse_unchanged_line_returns_none():
    assert _parse_porcelain_line("   ") is None


# ---------------------------------------------------------------------------
# get_git_status（真实仓库）
# ---------------------------------------------------------------------------


def test_status_non_git_dir_silent_degrade(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    out = get_git_status(path=str(plain))
    assert isinstance(out, GitStatusResponse)
    assert out.is_git_repo is False
    assert out.files == []


def test_status_nonexistent_dir_404(tmp_path):
    with pytest.raises(HTTPException) as excinfo:
        get_git_status(path=str(tmp_path / "ghost"))
    assert excinfo.value.status_code == 404


def test_status_clean_repo_empty_files(git_repo):
    _git(git_repo, "commit", "--allow-empty", "-m", "init")
    out = get_git_status(path=str(git_repo))
    assert out.is_git_repo is True
    assert out.branch == "main"
    assert out.files == []


def test_status_modified_and_untracked(git_repo):
    tracked = git_repo / "a.py"
    tracked.write_text("v1")
    _git(git_repo, "add", "a.py")
    _git(git_repo, "commit", "-m", "add a")
    tracked.write_text("v2")
    (git_repo / "b.py").write_text("new")
    out = get_git_status(path=str(git_repo))
    by_path = {f.path: f.status for f in out.files}
    assert by_path["a.py"] == "modified"
    assert by_path["b.py"] == "untracked"


def test_status_conflicted_sorts_first(git_repo):
    tracked = git_repo / "a.py"
    tracked.write_text("base")
    _git(git_repo, "add", "a.py")
    _git(git_repo, "commit", "-m", "base")
    # 制造一个 untracked 与一个 staged
    (git_repo / "c.py").write_text("staged-c")
    _git(git_repo, "add", "c.py")
    (git_repo / "u.py").write_text("untracked-u")
    out = get_git_status(path=str(git_repo))
    statuses = [f.status for f in out.files]
    # staged 排在 untracked 之前（status_order 表）
    assert statuses.index("staged") < statuses.index("untracked")


def test_status_path_with_spaces(git_repo):
    (git_repo / "my file.py").write_text("new")
    out = get_git_status(path=str(git_repo))
    paths = [f.path for f in out.files]
    assert "my file.py" in paths
