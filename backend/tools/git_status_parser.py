"""共享 git status porcelain v1 -z 解析器。

`git status --porcelain=v1 -z -b` 的输出同时被两处消费：
  - LLM 工具面：`backend/tools/git_tool.py` 的 `GitStatusTool`
  - 侧边栏面板：`backend/api/git_status_routes.py` 的 GET /git/status

两处各自解析会导致路径引号、rename 旧路径、ahead/behind 等细节漂移，
因此统一到此模块。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _parse_branch_header(record: str) -> Tuple[str, str, int, int]:
    """解析 ``## <branch>[...<upstream>][ [ahead N, behind M]]`` 行。

    分支名允许含点（如 ``release/v0.5.4``），因此不能用正则排除 ``.``；
    改为先按 ``...`` 切分上游，再剥离 ``[ahead/behind]`` 跟踪段。
    """
    head = record[3:] if record.startswith("## ") else record.lstrip("# ")
    track = ""
    marker = " ["
    if head.endswith("]") and marker in head:
        head, _, rest = head.rpartition(marker)
        track = rest[:-1]

    branch, _, upstream = head.partition("...")
    branch = branch.strip()
    upstream = upstream.strip()
    if branch == "HEAD (no branch)":
        branch = "HEAD"
    elif branch.startswith("No commits yet on "):
        branch = branch[len("No commits yet on ") :]

    ahead_match = re.search(r"ahead (\d+)", track)
    behind_match = re.search(r"behind (\d+)", track)
    return (
        branch,
        upstream,
        int(ahead_match.group(1)) if ahead_match else 0,
        int(behind_match.group(1)) if behind_match else 0,
    )


def parse_status_porcelain_v1_z(stdout: str) -> Dict[str, Any]:
    """解析 `git status --porcelain=v1 -z -b` 的标准输出。

    返回:
        branch: 分支名；detached HEAD 时为 "HEAD"，调用方按需归一化
        upstream: 上游分支名，无上游时为空串
        ahead / behind: 相对上游的领先/落后提交数
        entries: 文件条目，每项含
            index_status / worktree_status（已 strip 的单字符）
            path（新路径）
            old_path（仅 rename/copy 时存在）
    """
    records = stdout.split("\0")
    entries: List[Dict[str, str]] = []
    branch = ""
    upstream = ""
    ahead = 0
    behind = 0
    index = 0

    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue

        if record.startswith("##"):
            branch, upstream, ahead, behind = _parse_branch_header(record)
            continue

        # porcelain v1 -z: "XY <path>"；rename/copy 的下一段是旧路径
        index_status = record[:1].strip()
        worktree_status = record[1:2].strip()
        entry: Dict[str, str] = {
            "index_status": index_status,
            "worktree_status": worktree_status,
            "path": record[3:],
        }
        if (
            (index_status in ("R", "C") or worktree_status in ("R", "C"))
            and index < len(records)
            and records[index]
        ):
            entry["old_path"] = records[index]
            index += 1
        entries.append(entry)

    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "entries": entries,
    }
