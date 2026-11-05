"""共享 porcelain v1 -z 解析器单元测试。"""

from __future__ import annotations

import pytest

from backend.tools.git_status_parser import parse_status_porcelain_v1_z

pytestmark = pytest.mark.unit


def test_parses_branch_upstream_ahead_behind():
    parsed = parse_status_porcelain_v1_z(
        "## main...origin/main [ahead 2, behind 1]\0"
    )
    assert parsed["branch"] == "main"
    assert parsed["upstream"] == "origin/main"
    assert parsed["ahead"] == 2
    assert parsed["behind"] == 1


def test_branch_without_upstream():
    parsed = parse_status_porcelain_v1_z("## feature/x\0")
    assert parsed["branch"] == "feature/x"
    assert parsed["upstream"] == ""
    assert parsed["ahead"] == 0
    assert parsed["behind"] == 0


def test_branch_name_with_dots_not_truncated():
    parsed = parse_status_porcelain_v1_z(
        "## release/v0.5.4...origin/release/v0.5.4\0"
    )
    assert parsed["branch"] == "release/v0.5.4"
    assert parsed["upstream"] == "origin/release/v0.5.4"


def test_unborn_branch_header():
    parsed = parse_status_porcelain_v1_z("## No commits yet on main\0")
    assert parsed["branch"] == "main"


def test_detached_head_reports_head():
    parsed = parse_status_porcelain_v1_z("## HEAD (no branch)\0")
    assert parsed["branch"] == "HEAD"


def test_parses_entries_and_renames_old_path():
    stdout = "## main\0M  a.py\0R  new.py\0old.py\0?? b.py\0"
    entries = parse_status_porcelain_v1_z(stdout)["entries"]
    assert entries[0] == {
        "index_status": "M",
        "worktree_status": "",
        "path": "a.py",
    }
    assert entries[1]["path"] == "new.py"
    assert entries[1]["old_path"] == "old.py"
    assert entries[2]["path"] == "b.py"
    assert entries[2]["index_status"] == "?"


def test_unicode_and_space_paths_kept_verbatim():
    stdout = "## main\0?? 中文 文件.py\0"
    entries = parse_status_porcelain_v1_z(stdout)["entries"]
    assert entries[0]["path"] == "中文 文件.py"


def test_empty_stdout():
    parsed = parse_status_porcelain_v1_z("")
    assert parsed["entries"] == []
    assert parsed["branch"] == ""
