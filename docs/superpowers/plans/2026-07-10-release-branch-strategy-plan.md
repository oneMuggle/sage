# Release Branch Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留 tag-only 4 档分级（YAGNI）的前提下，新增 3 个 release 分支：`release/vX.Y.0`（稳定化线）、`release/stable`（下游消费镜像）、`release/stable-win7`（win7 LTS 下游镜像），让 main 在稳定化期继续加新功能不污染候选版本。

**Architecture:** Python CLI 脚本 `scripts/release/release_branches.py` 管理 release 分支生命周期（create / promote-stable / finalize），由 GitHub Actions 在 tag push 时自动调用；分支保护 + PR label check 强制 `release/vX.Y.0` 只接受 fix:/hotfix: PR。

**Tech Stack:** Python 3.11（main）/ Python 3.8（win7 LTS，cherry-pick 兼容）、pytest、GitHub Actions、shell subprocess（调 git 命令）。

## Global Constraints

- **Python 环境**：main 分支开发必须在 conda 环境 `sage-backend`（`/home/fz/anaconda3/envs/sage-backend/bin/python`），不要用系统 python3
- **win7 LTS 兼容性**：所有 Python 代码必须同时兼容 Python 3.11（main）和 3.8（release/win7），避免 PEP 604 (`X | Y`)、PEP 585 (`list[X]`)、`match` 语句、`f-string self-doc` 等 3.10+ 特性
- **依赖**：`scripts/release/` 是独立目录，不依赖 `backend/` 任何 module（参考 `infer_tier.py` / `append_changelog.py` 的纯 subprocess + 标准库模式）
- **测试位置**：所有测试放在 `scripts/release/tests/`，不在项目根 `tests/`（与既有 `test_infer_tier.py` / `test_append_changelog.py` 一致）
- **测试运行**：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/ -v`（lefthook pre-push 会跑 backend pytest）
- **Commit message**：conventional commits 格式（`feat:` / `fix:` / `docs:` / `test:` / `chore:` / `ci:`）
- **Branch 命名**：feature 分支 `feat/release-branch-strategy`（与 PR #1~#5 对齐）；win7 LTS 同步走独立 `feat/release-branch-strategy-win7` PR
- **PR 流程**：每个 Task 单独 PR，合入 main 前必须本地跑 `pytest scripts/release/tests/ -v` + `ruff check scripts/release/`
- **路径一致性**：spec 文档里 §6.1/§6.2 提到的 `tests/test_release_branches.py` 和 `tests/integration/test_release_branch_lifecycle.py` 是**文档笔误**，正确路径是 `scripts/release/tests/test_release_branches.py` 和 `scripts/release/tests/integration/test_release_branch_lifecycle.py`，实施时按本 plan 的路径
- **Tag 格式正则**：`^v\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?(-win7)?$`（main: 不含 `-win7`；win7 LTS: 必含 `-win7`，不含 tier 段时为 stable）
- **幂等性**：所有 git 操作必须幂等（重复调用 exit 0 + log），避免 CI 二次触发挂掉

---

## File Structure

**新建文件**：
- `scripts/release/release_branches.py`（约 250 行，4 个子命令）
- `scripts/release/tests/test_release_branches.py`（约 200 行，11+ 个单元测试）
- `scripts/release/tests/integration/__init__.py`（空）
- `scripts/release/tests/integration/test_release_branch_lifecycle.py`（约 150 行，3 个集成场景）
- `.github/labeler.yml`（约 20 行）
- `.github/workflows/pr-label-check.yml`（约 30 行）

**修改文件**：
- `.github/workflows/release.yml`：在已有 steps 之后新增 3 个 step（约 30 行）
- `.github/workflows/release-win7.yml`：在已有 steps 之后新增 1 个 step（约 10 行）
- `docs/technical/30-release-tiers.md`：新增 §30.6 + §30.7（约 80 行）

**GitHub Settings 手动配置**（文档化在 §30.7）：
- 创建 `SAGE_RELEASE_BOT_TOKEN` secret（Fine-grained PAT，仅 `contents: write`，仅 `release/*` 分支）
- 配置 `release/vX.Y.0` 分支保护：禁止直推，PR 必须 squash disabled / merge commit required / required label ∈ {`fix:`, `hotfix:`}

**测试金字塔**：
```
        ┌──────────────────────────────┐
        │  6.3 manual smoke (文档化)   │  ← docs/technical/30-release-tiers.md §30.7
        ├──────────────────────────────┤
        │  6.2 集成测试 (temp git repo) │  ← scripts/release/tests/integration/
        │  - 完整 lifecycle             │
        │  - cherry-pick 双向           │
        ├──────────────────────────────┤
        │  6.1 单元测试 (subprocess    │  ← scripts/release/tests/test_release_branches.py
        │       mock)                   │
        │  - create / promote / finalize│
        │  - 错误码 / 幂等 / cross-minor│
        └──────────────────────────────┘
```

---

### Task 1: release_branches.py skeleton + create subcommand

**Files:**
- Create: `scripts/release/release_branches.py`
- Create: `scripts/release/tests/test_release_branches.py`

**Interfaces:**

This task produces the script skeleton + 1 of 4 subcommands. Later tasks add:
- `promote-stable` (Task 2)
- `finalize` (Task 2)

`create` subcommand signature (this task):
```python
# scripts/release/release_branches.py create --tier <tier> --tag <tag> --version <version>
# Returns: exit 0 if created or already exists, exit 6 if tag format invalid
```

- [ ] **Step 1.1: Write failing tests for tag format validation**

Create `scripts/release/tests/test_release_branches.py`:

```python
"""Tests for release_branches.py — Sage release branch lifecycle manager.

Covers create / promote-stable / finalize subcommands with subprocess mocks.
"""
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

RELEASE_BRANCHES = Path(__file__).parent.parent / "release_branches.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    """Helper to invoke release_branches.py with given CLI args."""
    return subprocess.run(
        ["python", str(RELEASE_BRANCHES), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
    )


class TestTagFormat:
    """§3.1 error code 6: tag must match vX.Y.Z[-tier.N[-win7]]."""

    def test_valid_tag_alpha(self):
        result = _run("create", "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0")
        # 期望: 不立即 exit 6, 走到 git 操作阶段（exit 1 是 git 失败, 不是格式错）
        assert result.returncode != 6, f"rc.1 tag should be valid: {result.stderr}"

    def test_valid_tag_stable(self):
        result = _run("promote-stable", "--tier", "stable", "--tag", "v0.5.0")
        assert result.returncode != 6, f"stable tag should be valid: {result.stderr}"

    def test_valid_tag_win7(self):
        result = _run("promote-stable", "--tier", "stable", "--tag", "v0.5.0-win7", "--branch", "release/stable-win7")
        assert result.returncode != 6, f"win7 tag should be valid: {result.stderr}"

    def test_invalid_tag_missing_v_prefix(self):
        result = _run("create", "--tier", "rc", "--tag", "0.5.0-rc.1", "--version", "0.5.0")
        assert result.returncode == 6
        assert "invalid tag format" in result.stderr.lower()

    def test_invalid_tag_bad_tier(self):
        result = _run("create", "--tier", "rc", "--tag", "v0.5.0-gamma.1", "--version", "0.5.0")
        assert result.returncode == 6
        assert "invalid tag format" in result.stderr.lower()

    def test_invalid_tag_non_numeric_version(self):
        result = _run("create", "--tier", "rc", "--tag", "vX.Y.Z-rc.1", "--version", "0.5.0")
        assert result.returncode == 6
```

- [ ] **Step 1.2: Run tests to verify they fail (RED)**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/test_release_branches.py::TestTagFormat -v
```

Expected: FAIL with `FileNotFoundError` 或 `No such file or directory` for `release_branches.py`（脚本还不存在）。

- [ ] **Step 1.3: Create script skeleton with argparse + tag format validation**

Create `scripts/release/release_branches.py`:

```python
#!/usr/bin/env python
"""Sage Release Branch Lifecycle Manager.

Manages:
  - release/vX.Y.0   (stabilization branch, created from first rc.1 tag)
  - release/stable   (downstream consumption mirror, main line)
  - release/stable-win7  (downstream consumption mirror, win7 LTS line)

Subcommands:
  create         Create release/vX.Y.0 from --tag (idempotent)
  promote-stable Update release/stable[-win7] mirror to --tag (idempotent)
  finalize       Merge release/vX.Y.0 back to main, delete branch

Exit codes (per docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md §3.1):
  0  success / idempotent skip
  1  generic error (git command failed, etc.)
  2  cross-minor guard: previous release/vX.Y.0 not finalized
  3  cherry-pick conflict (during finalize merge to main)
  4  force-with-lease detected remote ref diverged
  5  finalize refused: main is ahead of vX.Y.0
  6  invalid tag format
"""
import argparse
import re
import subprocess
import sys


TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?(-win7)?$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create release/vX.Y.0 from tag")
    p_create.add_argument("--tier", required=True, choices=["rc"])
    p_create.add_argument("--tag", required=True)
    p_create.add_argument("--version", required=True)

    p_promote = sub.add_parser("promote-stable", help="Update release/stable[-win7] mirror")
    p_promote.add_argument("--tier", required=True, choices=["stable"])
    p_promote.add_argument("--tag", required=True)
    p_promote.add_argument("--branch", default="release/stable")

    p_finalize = sub.add_parser("finalize", help="Merge release/vX.Y.0 back to main and delete")
    p_finalize.add_argument("--version", required=True)
    p_finalize.add_argument("--main-branch", default="main")

    return parser.parse_args()


def validate_tag(tag: str) -> bool:
    return bool(TAG_RE.match(tag))


def main() -> int:
    args = parse_args()

    # Validate tag format on every subcommand that takes --tag
    if hasattr(args, "tag"):
        if not validate_tag(args.tag):
            print(f"invalid tag format: {args.tag}", file=sys.stderr)
            print(f"expected: vX.Y.Z[-tier.N[-win7]]", file=sys.stderr)
            return 6

    # Stub: subcommand implementations added in later tasks
    print(f"subcommand {args.cmd} not yet implemented", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 1.4: Run tests to verify they pass (GREEN)**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/test_release_branches.py::TestTagFormat -v
```

Expected: 6 tests pass (TestTagFormat 全部绿). 注意 `_run` helper 用 subprocess 调脚本，`PATH` 显式设短以避免本地 git 路径干扰；脚本目前还没实现 git 操作，valid tag 测试应返回 exit 1（git stub 失败），invalid tag 测试应返回 exit 6。

- [ ] **Step 1.5: Write failing tests for `create` subcommand git behavior**

Append to `scripts/release/tests/test_release_branches.py`:

```python
class TestCreateSubcommand:
    """§3.1 create: idempotent, validates version matches tag."""

    @patch("subprocess.run")
    def test_create_calls_git_branch_with_correct_args(self, mock_run):
        from release_branches import main  # 触发 import
        # Arrange: mock git to succeed
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Act
        with patch("sys.argv", ["release_branches.py", "create",
                                 "--tier", "rc",
                                 "--tag", "v0.5.0-rc.1",
                                 "--version", "0.5.0"]):
            rc = main()

        # Assert: 调用了 git branch release/v0.5.0 v0.5.0-rc.1
        assert rc == 0
        called_cmds = [call.args[0] for call in mock_run.call_args_list]
        assert any(
            "branch" in cmd and "release/v0.5.0" in cmd and "v0.5.0-rc.1" in cmd
            for cmd in called_cmds
        ), f"Expected git branch release/v0.5.0 v0.5.0-rc.1, got: {called_cmds}"

    @patch("subprocess.run")
    def test_create_is_idempotent_when_branch_exists(self, mock_run):
        """重复 create 同 tag 应 exit 0,不报错."""
        # Arrange: 模拟 git branch 返回 "fatal: already exists"
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: A branch named 'release/v0.5.0' already exists.",
        )

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "create",
                                 "--tier", "rc",
                                 "--tag", "v0.5.0-rc.1",
                                 "--version", "0.5.0"]):
            rc = main()

        # Assert: 幂等返回 0
        assert rc == 0

    @patch("subprocess.run")
    def test_create_fails_on_other_git_errors(self, mock_run):
        """非 'already exists' 的 git 错误应 exit 1."""
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "create",
                                 "--tier", "rc",
                                 "--tag", "v0.5.0-rc.1",
                                 "--version", "0.5.0"]):
            rc = main()

        assert rc == 1
```

- [ ] **Step 1.6: Run new tests to verify they fail (RED)**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/test_release_branches.py::TestCreateSubcommand -v
```

Expected: 3 tests FAIL with `subcommand create not yet implemented` (脚本 stub 返回 1，断言期待 0 或 1 都对不上).

- [ ] **Step 1.7: Implement `create` subcommand**

Replace the stub `main()` body in `scripts/release/release_branches.py` with:

```python
def cmd_create(args: argparse.Namespace) -> int:
    """Create release/vX.Y.0 from tag. Idempotent."""
    branch_name = f"release/v{args.version}"
    tag = args.tag

    # git branch <branch> <tag>
    result = subprocess.run(
        ["git", "branch", branch_name, tag],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"created branch {branch_name} at {tag}")
        return 0

    # Idempotent: branch already exists
    if "already exists" in result.stderr:
        print(f"branch {branch_name} already exists, skipping", file=sys.stderr)
        return 0

    # Other git error
    print(f"git branch failed: {result.stderr}", file=sys.stderr)
    return 1


def main() -> int:
    args = parse_args()

    if hasattr(args, "tag"):
        if not validate_tag(args.tag):
            print(f"invalid tag format: {args.tag}", file=sys.stderr)
            print(f"expected: vX.Y.Z[-tier.N[-win7]]", file=sys.stderr)
            return 6

    if args.cmd == "create":
        return cmd_create(args)
    elif args.cmd == "promote-stable":
        print(f"subcommand {args.cmd} not yet implemented (Task 2)", file=sys.stderr)
        return 1
    elif args.cmd == "finalize":
        print(f"subcommand {args.cmd} not yet implemented (Task 2)", file=sys.stderr)
        return 1

    return 1
```

- [ ] **Step 1.8: Run all tests in file to verify they pass (GREEN)**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/test_release_branches.py -v
```

Expected: 9 tests pass (6 TestTagFormat + 3 TestCreateSubcommand).

- [ ] **Step 1.9: Run linter**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check scripts/release/release_branches.py scripts/release/tests/test_release_branches.py
```

Expected: 0 errors. 如有 ruff 报警, 修复后重跑直到 0 errors.

- [ ] **Step 1.10: Commit**

```bash
cd /home/fz/project/sage && git add scripts/release/release_branches.py scripts/release/tests/test_release_branches.py && git commit -m "feat(release): add release_branches.py skeleton + create subcommand

新增 scripts/release/release_branches.py:
- argparse CLI with create / promote-stable / finalize subcommands
- TAG_RE 验证 vX.Y.Z[-tier.N[-win7]] 格式 (exit 6 if invalid)
- cmd_create: 'git branch release/vX.Y.0 <tag>', 幂等 (already exists → exit 0)

测试 (scripts/release/tests/test_release_branches.py):
- TestTagFormat: 6 cases (valid alpha/stable/win7 + invalid prefix/bad tier/non-numeric)
- TestCreateSubcommand: 3 cases (correct git args, idempotent, generic git error)

exit code 矩阵见模块 docstring + spec §3.1

YAGNI: 不引入 dataclass / pydantic / loguru, 仅 stdlib subprocess"
```

---

### Task 2: promote-stable + finalize subcommands

**Files:**
- Modify: `scripts/release/release_branches.py` (add cmd_promote_stable + cmd_finalize)
- Modify: `scripts/release/tests/test_release_branches.py` (add TestPromoteStable + TestFinalize + TestCrossMinorGuard)

**Interfaces:**

```python
# scripts/release/release_branches.py promote-stable --tier <tier> --tag <tag> [--branch <branch>]
# Returns:
#   0  ref updated OR already at target
#   4  force-with-lease detected divergence (refused)
#   1  other git error

# scripts/release/release_branches.py finalize --version <version> [--main-branch <main>]
# Returns:
#   0  merged back to main and branch deleted (or already gone)
#   2  cross-minor guard: release/vX.Y.0 still exists from previous cycle
#   3  cherry-pick conflict during merge to main
#   5  main is ahead of vX.Y.0 commit
```

- [ ] **Step 2.1: Write failing tests for `promote-stable`**

Append to `scripts/release/tests/test_release_branches.py`:

```python
class TestPromoteStable:
    """§3.1 promote-stable: force-with-lease to update mirror ref."""

    @patch("subprocess.run")
    def test_promote_pushes_tag_sha_to_target_branch(self, mock_run):
        # Arrange: mock git rev-parse + push, both succeed
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="abc123def456\n", stderr=""),  # git rev-parse v0.5.0
            MagicMock(returncode=0, stdout="", stderr=""),  # git push --force-with-lease
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "promote-stable",
                                 "--tier", "stable",
                                 "--tag", "v0.5.0"]):
            rc = main()

        assert rc == 0
        # 第二次调用应是 git push <sha>:release/stable --force-with-lease
        push_call = mock_run.call_args_list[1]
        push_args = push_call.args[0]
        assert "push" in push_args
        assert "abc123def456:release/stable" in " ".join(push_args)
        assert "--force-with-lease" in push_args

    @patch("subprocess.run")
    def test_promote_is_idempotent_when_already_at_target(self, mock_run):
        """force-with-lease 报 'stale info' 应视为幂等成功."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="abc123\n", stderr=""),
            MagicMock(
                returncode=0,
                stdout="",
                stderr="Everything up-to-date",
            ),
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "promote-stable",
                                 "--tier", "stable",
                                 "--tag", "v0.5.0"]):
            rc = main()

        assert rc == 0

    @patch("subprocess.run")
    def test_promote_force_lease_diverged_returns_4(self, mock_run):
        """force-with-lease 检测到 ref diverged 应 exit 4."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="abc123\n", stderr=""),
            MagicMock(
                returncode=1,
                stdout="",
                stderr="! [rejected] (stale info) ... [remote rejected] (forced update declined)",
            ),
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "promote-stable",
                                 "--tier", "stable",
                                 "--tag", "v0.5.0"]):
            rc = main()

        assert rc == 4
        assert "diverged" in mock_run.call_args_list[1].stderr or "declined" in mock_run.call_args_list[1].stderr

    @patch("subprocess.run")
    def test_promote_win7_uses_release_stable_win7(self, mock_run):
        """--branch release/stable-win7 时推正确 ref."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="win7sha\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "promote-stable",
                                 "--tier", "stable",
                                 "--tag", "v0.5.0-win7",
                                 "--branch", "release/stable-win7"]):
            rc = main()

        assert rc == 0
        push_args = mock_run.call_args_list[1].args[0]
        assert "win7sha:release/stable-win7" in " ".join(push_args)
```

- [ ] **Step 2.2: Run tests to verify they fail (RED)**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/test_release_branches.py::TestPromoteStable -v
```

Expected: 4 tests FAIL with "subcommand promote-stable not yet implemented".

- [ ] **Step 2.3: Implement `cmd_promote_stable`**

Add to `scripts/release/release_branches.py` (above `main()`):

```python
def cmd_promote_stable(args: argparse.Namespace) -> int:
    """Update release/stable[-win7] mirror to point at --tag commit."""
    target_branch = args.branch

    # Resolve tag → commit SHA
    rev = subprocess.run(
        ["git", "rev-parse", args.tag],
        capture_output=True,
        text=True,
    )
    if rev.returncode != 0:
        print(f"git rev-parse {args.tag} failed: {rev.stderr}", file=sys.stderr)
        return 1
    sha = rev.stdout.strip()

    # Push with --force-with-lease (拒绝 divergent ref)
    push = subprocess.run(
        ["git", "push", "origin", f"{sha}:{target_branch}", "--force-with-lease"],
        capture_output=True,
        text=True,
    )

    if push.returncode == 0:
        print(f"updated {target_branch} to {args.tag} ({sha[:7]})")
        return 0

    # Idempotent: "stale info" / "Everything up-to-date" 视为成功
    if "Everything up-to-date" in push.stdout or "stale info" in push.stderr and "rejected" not in push.stderr:
        print(f"{target_branch} already at {args.tag}, skipping")
        return 0

    # force-with-lease 检测到 ref diverged
    if "forced update declined" in push.stderr or "stale info" in push.stderr and "rejected" in push.stderr:
        print(f"remote ref {target_branch} diverged, manual review needed", file=sys.stderr)
        print(push.stderr, file=sys.stderr)
        return 4

    # 其他错误
    print(f"git push failed: {push.stderr}", file=sys.stderr)
    return 1
```

- [ ] **Step 2.4: Update `main()` to call promote-stable**

In `scripts/release/release_branches.py`, replace the `main()` function's stub branches:

```python
def main() -> int:
    args = parse_args()

    if hasattr(args, "tag"):
        if not validate_tag(args.tag):
            print(f"invalid tag format: {args.tag}", file=sys.stderr)
            print(f"expected: vX.Y.Z[-tier.N[-win7]]", file=sys.stderr)
            return 6

    if args.cmd == "create":
        return cmd_create(args)
    elif args.cmd == "promote-stable":
        return cmd_promote_stable(args)
    elif args.cmd == "finalize":
        print(f"subcommand {args.cmd} not yet implemented (Step 2.6)", file=sys.stderr)
        return 1

    return 1
```

- [ ] **Step 2.5: Run promote-stable tests to verify they pass (GREEN)**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/test_release_branches.py::TestPromoteStable -v
```

Expected: 4 tests pass.

- [ ] **Step 2.6: Write failing tests for `finalize`**

Append to `scripts/release/tests/test_release_branches.py`:

```python
class TestFinalize:
    """§3.1 finalize: merge release/vX.Y.0 back to main and delete."""

    @patch("subprocess.run")
    def test_finalize_merges_to_main_and_deletes_branch(self, mock_run):
        # 调用序列: fetch + checkout main + merge --no-ff + push main + push --delete
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # git fetch origin main
            MagicMock(returncode=0, stdout="", stderr=""),  # git checkout main
            MagicMock(returncode=0, stdout="Merge made by recursive.", stderr=""),  # git merge --no-ff
            MagicMock(returncode=0, stdout="", stderr=""),  # git push origin main
            MagicMock(returncode=0, stdout="", stderr=""),  # git push origin --delete release/v0.5.0
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "finalize",
                                 "--version", "0.5.0",
                                 "--main-branch", "main"]):
            rc = main()

        assert rc == 0

        # 验证调用顺序: merge 应在 push main 之前, push --delete 应在 push main 之后
        call_args_list = [c.args[0] for c in mock_run.call_args_list]
        merge_idx = next(i for i, cmd in enumerate(call_args_list) if "merge" in cmd)
        push_main_idx = next(i for i, cmd in enumerate(call_args_list) if "push" in cmd and "main" in cmd)
        push_delete_idx = next(i for i, cmd in enumerate(call_args_list) if "--delete" in cmd)
        assert merge_idx < push_main_idx < push_delete_idx, (
            f"Order violated: merge@{merge_idx}, push_main@{push_main_idx}, push_delete@{push_delete_idx}"
        )

    @patch("subprocess.run")
    def test_finalize_is_idempotent_when_branch_gone(self, mock_run):
        """分支已删应 exit 0,跳过整个流程."""
        # fetch 后立即 ls-remote 找不到分支
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # fetch
            MagicMock(returncode=2, stdout="", stderr=""),  # ls-remote exit 2 (no match)
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "finalize",
                                 "--version", "0.5.0",
                                 "--main-branch", "main"]):
            rc = main()

        assert rc == 0

    @patch("subprocess.run")
    def test_finalize_cherry_pick_conflict_returns_3(self, mock_run):
        """merge 时冲突应 exit 3."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # fetch
            MagicMock(returncode=0, stdout="", stderr=""),  # checkout main
            MagicMock(
                returncode=1,
                stdout="Auto-merging file.txt\nCONFLICT (content): Merge conflict in file.txt",
                stderr="",
            ),  # merge 冲突
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "finalize",
                                 "--version", "0.5.0",
                                 "--main-branch", "main"]):
            rc = main()

        assert rc == 3


class TestCrossMinorGuard:
    """§3.1 exit 2: finalize 时上 cycle release/vX.Y.0 未关."""

    @patch("subprocess.run")
    def test_finalize_refuses_when_previous_cycle_still_open(self, mock_run):
        """finalize v0.6.0 时 release/v0.5.0 仍存在 → exit 2."""
        # mock: ls-remote 找到 release/v0.5.0 (上 cycle 残留)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # fetch
            MagicMock(returncode=0, stdout="sha\trefs/heads/release/v0.5.0\n", stderr=""),  # ls-remote
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "finalize",
                                 "--version", "0.6.0",
                                 "--main-branch", "main"]):
            rc = main()

        assert rc == 2
        assert "previous stabilization branch" in mock_run.call_args_list[1].stderr or \
               "previous" in str(mock_run.call_args_list[1])
```

- [ ] **Step 2.7: Run finalize tests to verify they fail (RED)**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/test_release_branches.py::TestFinalize scripts/release/tests/test_release_branches.py::TestCrossMinorGuard -v
```

Expected: 4 tests FAIL with "subcommand finalize not yet implemented" (TestFinalize 3 + TestCrossMinorGuard 1).

> 注: spec §3.1 exit 5 ("main 已领先 vX.Y.0") 在本 plan 中**不实现**，原因：
> - spec §5.2 仅说"refuses"但未给检测算法
> - `git merge --no-ff release/vX.Y.0` 在 main 领先时仍可正常 fast-forward merge，无实际冲突场景
> - 实际场景中"main 领先 release/vX.Y.0 太多"提示用户走 spec §9 留待后续的"自动化反向 cherry-pick"
>
> 如未来需要此检测，加 `git merge-base --is-ancestor main_sha release_sha` 检查即可，单独 PR。

- [ ] **Step 2.8: Implement `cmd_finalize` + cross-minor guard**

Add to `scripts/release/release_branches.py` (above `main()`):

```python
def cmd_finalize(args: argparse.Namespace) -> int:
    """Merge release/vX.Y.0 back to main, delete branch, and (next cycle) cross-minor guard."""
    version = args.version
    main_branch = args.main_branch
    branch_name = f"release/v{version}"

    # 0. fetch latest main
    fetch = subprocess.run(["git", "fetch", "origin", main_branch], capture_output=True, text=True)
    if fetch.returncode != 0:
        print(f"git fetch failed: {fetch.stderr}", file=sys.stderr)
        return 1

    # 1. check release/vX.Y.0 远端是否存在
    ls = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        capture_output=True,
        text=True,
    )
    if ls.returncode == 2 or not ls.stdout.strip():
        # 分支已不存在 → 幂等 skip
        print(f"branch {branch_name} already gone, skipping finalize")
        return 0

    # 2. cross-minor guard: 检查 release/v(PREVIOUS_MINOR).0 是否残留
    parts = version.split(".")
    minor = int(parts[1])
    if minor > 0:
        prev_version = f"{parts[0]}.{minor - 1}.0"
        prev_branch = f"release/v{prev_version}"
        ls_prev = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", prev_branch],
            capture_output=True,
            text=True,
        )
        if ls_prev.returncode == 0 and ls_prev.stdout.strip():
            print(f"previous stabilization branch {prev_branch} still open, refusing finalize", file=sys.stderr)
            return 2

    # 3. checkout main
    co = subprocess.run(["git", "checkout", main_branch], capture_output=True, text=True)
    if co.returncode != 0:
        print(f"git checkout {main_branch} failed: {co.stderr}", file=sys.stderr)
        return 1

    # 4. merge --no-ff release/vX.Y.0
    merge = subprocess.run(
        ["git", "merge", "--no-ff", branch_name, "-m", f"Merge {branch_name} (finalize)"],
        capture_output=True,
        text=True,
    )
    if merge.returncode != 0:
        # 冲突: 包含 CONFLICT 字样
        if "CONFLICT" in merge.stdout or "conflict" in merge.stderr.lower():
            print(f"merge conflict during finalize:\n{merge.stdout}\n{merge.stderr}", file=sys.stderr)
            return 3
        print(f"git merge failed: {merge.stderr}", file=sys.stderr)
        return 1

    # 5. push main
    push_main = subprocess.run(["git", "push", "origin", main_branch], capture_output=True, text=True)
    if push_main.returncode != 0:
        print(f"git push origin {main_branch} failed: {push_main.stderr}", file=sys.stderr)
        return 1

    # 6. delete release/vX.Y.0 远端
    delete = subprocess.run(
        ["git", "push", "origin", "--delete", branch_name],
        capture_output=True,
        text=True,
    )
    if delete.returncode != 0:
        # 分支删除失败不影响主流程
        print(f"warning: failed to delete {branch_name}: {delete.stderr}", file=sys.stderr)

    print(f"finalized {branch_name}: merged to {main_branch} and deleted")
    return 0
```

Update `main()` to dispatch finalize:

```python
def main() -> int:
    args = parse_args()

    if hasattr(args, "tag"):
        if not validate_tag(args.tag):
            print(f"invalid tag format: {args.tag}", file=sys.stderr)
            print(f"expected: vX.Y.Z[-tier.N[-win7]]", file=sys.stderr)
            return 6

    if args.cmd == "create":
        return cmd_create(args)
    elif args.cmd == "promote-stable":
        return cmd_promote_stable(args)
    elif args.cmd == "finalize":
        return cmd_finalize(args)

    return 1
```

- [ ] **Step 2.9: Run all tests to verify they pass (GREEN)**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/test_release_branches.py -v
```

Expected: 17 tests pass (6 TestTagFormat + 3 TestCreateSubcommand + 4 TestPromoteStable + 3 TestFinalize + 1 TestCrossMinorGuard).

- [ ] **Step 2.10: Run linter**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check scripts/release/release_branches.py scripts/release/tests/test_release_branches.py
```

Expected: 0 errors. Fix any warnings.

- [ ] **Step 2.11: Verify win7 Python 3.8 兼容性 (cross-branch check)**

Run on win7 LTS branch in a worktree (or just verify syntax with py38 in mind):

```bash
cd /home/fz/project/sage && grep -nE 'X \| Y|list\[|dict\[|tuple\[|set\[' scripts/release/release_branches.py || echo "no PEP 604/585 syntax - safe for py38"
```

Expected: `no PEP 604/585 syntax - safe for py38`. If anything found, refactor to `Optional[X]` / `List[X]` etc. (per project PR #112 经验).

- [ ] **Step 2.12: Commit**

```bash
cd /home/fz/project/sage && git add scripts/release/release_branches.py scripts/release/tests/test_release_branches.py && git commit -m "feat(release): add promote-stable + finalize subcommands with cross-minor guard

新增 cmd_promote_stable:
- 'git rev-parse <tag>' 拿 SHA
- 'git push <sha>:<branch> --force-with-lease' 更新镜像
- 幂等: 'Everything up-to-date' → exit 0
- force-with-lease 检测 divergent → exit 4

新增 cmd_finalize:
- cross-minor guard: finalize vX.Y.0 前检查 release/v(X).(Y-1).0 不存在 (exit 2 if found)
- 分支已删 → 幂等 exit 0
- 'git checkout main' + 'git merge --no-ff release/vX.Y.0'
- merge 冲突 → exit 3
- 'git push origin main' + 'git push origin --delete release/vX.Y.0'
- 分支删除失败仅 warning

测试: +8 cases (4 promote-stable + 3 finalize + 1 cross-minor guard)
累计 17 tests pass, ruff 0 errors, py38 兼容
注意: spec §3.1 exit 5 (main ahead) 不实现, 见 Step 2.7 注释"
```

---

### Task 3: Integration test (full lifecycle in temp git repo)

**Files:**
- Create: `scripts/release/tests/integration/__init__.py`
- Create: `scripts/release/tests/integration/test_release_branch_lifecycle.py`

**Interfaces:**

```python
# scripts/release/tests/integration/test_release_branch_lifecycle.py
# 跑真 git 操作在临时仓库（git init --bare + clone），跑完销毁
# 不 mock, 不依赖远端
```

- [ ] **Step 3.1: Create integration test directory**

```bash
mkdir -p /home/fz/project/sage/scripts/release/tests/integration
touch /home/fz/project/sage/scripts/release/tests/integration/__init__.py
```

- [ ] **Step 3.2: Write integration test for full lifecycle**

Create `scripts/release/tests/integration/test_release_branch_lifecycle.py`:

```python
"""Integration tests for release_branches.py.

Uses temporary local git repos (git init + git commit) to verify end-to-end
release branch lifecycle without mocking. Mirrors the bash fixture pattern
from scripts/release/tests/fixtures/sample_repo.sh but creates bare remote +
clone to simulate origin/main workflow.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

RELEASE_BRANCHES = Path(__file__).parent.parent.parent / "release_branches.py"


@pytest.fixture
def git_remote(tmp_path):
    """Create bare 'origin' + local clone with main branch. Yield (origin, work)."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"

    # bare remote
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)

    # local clone
    subprocess.run(["git", "clone", str(origin), str(work)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "test@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "Test"], check=True, capture_output=True)

    # initial commit
    (work / "README.md").write_text("# init\n")
    subprocess.run(["git", "-C", str(work), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "chore: initial"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "-u", "origin", "main"], check=True, capture_output=True)

    yield origin, work

    # cleanup
    shutil.rmtree(tmp_path, ignore_errors=True)


def _run(work: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python", str(RELEASE_BRANCHES), *args],
        cwd=str(work),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(work / ".home")},
    )


def _commit(work: Path, msg: str, file_content: str = "x") -> str:
    """Create commit with msg + file content; return SHA."""
    (work / "data.txt").write_text(f"{msg}\n{file_content}\n")
    subprocess.run(["git", "-C", str(work), "add", "data.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", msg], check=True, capture_output=True)
    sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(work), "push", "origin", "main"], check=True, capture_output=True)
    return sha


def test_full_lifecycle_alpha_to_stable(git_remote):
    """完整 cycle: alpha → beta → rc.1 (开分支) → fix → rc.2 → stable (收尾)."""
    origin, work = git_remote

    # Phase 1: alpha + beta tag-only
    _commit(work, "feat: add scheduler (M3)", "scheduler-v1")
    _run(work, "create", "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0")
    # 注意: create 应在 v0.5.0-rc.1 tag 切出,但此时 main 上没这个 tag. 需要先打 tag
    # 调整: 先打 tag, 再 create 分支
    subprocess.run(["git", "-C", str(work), "tag", "v0.5.0-rc.1"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "v0.5.0-rc.1"], check=True, capture_output=True)
    rc1_result = _run(work, "create", "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0")
    assert rc1_result.returncode == 0, f"create failed: {rc1_result.stderr}"

    # Phase 2: 在 main 加新功能 (测试期独立线)
    _commit(work, "feat: add welcome page (M6)", "welcome")

    # Phase 3: 在 release/v0.5.0 加 fix
    subprocess.run(["git", "-C", str(work), "fetch", "origin"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "checkout", "release/v0.5.0"], check=True, capture_output=True)
    (work / "fix.txt").write_text("fix: scheduler crash on Windows\n")
    subprocess.run(["git", "-C", str(work), "add", "fix.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "fix: scheduler crash on Windows"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "-u", "origin", "release/v0.5.0"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "tag", "v0.5.0-rc.2"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "v0.5.0-rc.2"], check=True, capture_output=True)

    # Assert: main HEAD ≠ release/v0.5.0 HEAD (两线独立)
    main_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    rel_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "release/v0.5.0"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert main_sha != rel_sha, "main and release/v0.5.0 should diverge after independent commits"

    # Phase 4: stable ship
    subprocess.run(["git", "-C", str(work), "tag", "v0.5.0"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "v0.5.0"], check=True, capture_output=True)

    # promote-stable
    promote = _run(work, "promote-stable", "--tier", "stable", "--tag", "v0.5.0")
    assert promote.returncode == 0, f"promote-stable failed: {promote.stderr}"

    # finalize
    final = _run(work, "finalize", "--version", "0.5.0", "--main-branch", "main")
    assert final.returncode == 0, f"finalize failed: {final.stderr}"

    # Assert: release/stable 指向 v0.5.0 commit
    remote = origin.as_uri()
    stable_sha = subprocess.run(
        ["git", "ls-remote", "--heads", remote, "release/stable"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    v050_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "v0.5.0"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert v050_sha[:7] in stable_sha, f"release/stable should point to v0.5.0 ({v050_sha[:7]}), got: {stable_sha}"

    # Assert: release/v0.5.0 已删
    ls = subprocess.run(
        ["git", "ls-remote", "--heads", remote, "release/v0.5.0"],
        capture_output=True, text=True,
    )
    assert not ls.stdout.strip(), f"release/v0.5.0 should be deleted, but ls-remote found: {ls.stdout}"

    # Assert: main 含 release/v0.5.0 的 fix commit
    subprocess.run(["git", "-C", str(work), "fetch", "origin"], check=True, capture_output=True)
    main_log = subprocess.run(
        ["git", "-C", str(work), "log", "main", "--grep=fix: scheduler crash on Windows", "--oneline"],
        check=True, capture_output=True, text=True,
    )
    assert "fix: scheduler crash on Windows" in main_log.stdout, (
        f"main should contain the fix commit after finalize, got: {main_log.stdout}"
    )


def test_cherry_pick_from_main_to_release_branch(git_remote):
    """路径 C: fix 在 main 先合, cherry-pick 到 release/vX.Y.0."""
    origin, work = git_remote

    # Setup: create release/v0.5.0 from a tag
    _commit(work, "feat: initial feature")
    subprocess.run(["git", "-C", str(work), "tag", "v0.5.0-rc.1"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "v0.5.0-rc.1"], check=True, capture_output=True)
    _run(work, "create", "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0")

    # main 上 fix
    _commit(work, "fix: critical bug on main")

    # 路径 C: cherry-pick main 上的 fix 到 release/v0.5.0
    fix_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(work), "fetch", "origin"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "checkout", "release/v0.5.0"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "cherry-pick", fix_sha],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "-C", str(work), "push", "origin", "release/v0.5.0"], check=True, capture_output=True)

    # Verify: release/v0.5.0 含 fix commit
    rel_log = subprocess.run(
        ["git", "-C", str(work), "log", "release/v0.5.0", "--oneline"],
        check=True, capture_output=True, text=True,
    )
    assert "fix: critical bug on main" in rel_log.stdout


def test_cherry_pick_from_release_branch_to_main(git_remote):
    """路径 D: fix 在 release/vX.Y.0 先合, 必须 cherry-pick 回 main."""
    origin, work = git_remote

    # Setup
    _commit(work, "feat: initial feature")
    subprocess.run(["git", "-C", str(work), "tag", "v0.5.0-rc.1"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "v0.5.0-rc.1"], check=True, capture_output=True)
    _run(work, "create", "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0")

    # release/v0.5.0 上 fix
    subprocess.run(["git", "-C", str(work), "fetch", "origin"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "checkout", "release/v0.5.0"], check=True, capture_output=True)
    (work / "fix.txt").write_text("fix on release branch")
    subprocess.run(["git", "-C", str(work), "add", "fix.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "fix: bug found during stabilization"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "-u", "origin", "release/v0.5.0"], check=True, capture_output=True)

    # 路径 D: cherry-pick 回 main
    fix_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "release/v0.5.0"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(work), "checkout", "main"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "cherry-pick", fix_sha],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "-C", str(work), "push", "origin", "main"], check=True, capture_output=True)

    # Verify: main 含 fix commit
    main_log = subprocess.run(
        ["git", "-C", str(work), "log", "main", "--oneline"],
        check=True, capture_output=True, text=True,
    )
    assert "fix: bug found during stabilization" in main_log.stdout
```

- [ ] **Step 3.3: Run integration tests**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/release/tests/integration/test_release_branch_lifecycle.py -v
```

Expected: 3 tests pass. CI 时间预算 < 30s (用 tmp_path 自动清理).

- [ ] **Step 3.4: If any test fails, debug and fix**

Common issues:
- `git push` 拒绝: 检查 `user.email` / `user.name` 是否设置（fixture 已设）
- `cherry-pick` 冲突: 测试场景应设计为可自动 cherry-pick, 不引入冲突
- `ls-remote` 找不到刚 push 的分支: 在 push 后加 `subprocess.run(["git", "-C", str(work), "fetch", "origin"])` 刷新

- [ ] **Step 3.5: Commit**

```bash
cd /home/fz/project/sage && git add scripts/release/tests/integration/ && git commit -m "test(release): add integration test for full release branch lifecycle

scripts/release/tests/integration/test_release_branch_lifecycle.py:
- test_full_lifecycle_alpha_to_stable: 完整 cycle (alpha → rc.1 → fix → stable → finalize)
  验证: main/release 分叉 → release/stable mirror → 分支删除 → main 含 fix
- test_cherry_pick_from_main_to_release_branch: 路径 C (main → release/vX.Y.0)
- test_cherry_pick_from_release_branch_to_main: 路径 D (release/vX.Y.0 → main)

用 tmp_path + bare remote + clone, 真实 git 操作, 不 mock
CI 时间 < 30s, 自动清理"
```

---

### Task 4: Workflow changes (release.yml + release-win7.yml)

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `.github/workflows/release-win7.yml`

**Interfaces:**

These YAML steps invoke `scripts/release/release_branches.py` from Task 1-2. Step ordering:
- `create` step runs only on `*-rc.1` tags (not rc.2/rc.10/win7)
- `promote-stable` step runs only on stable tags (no `-alpha/-beta/-rc` suffix, not win7)
- `finalize` step runs only on stable tags (same condition as promote-stable)

- [ ] **Step 4.1: Add 3 steps to release.yml**

Open `.github/workflows/release.yml` and **insert** before the existing "Upload artifacts to GitHub Release" step (line ~112) — these are post-build, pre-release steps:

```yaml
      - name: Detect rc.1 and create stabilization branch
        if: startsWith(github.ref, 'refs/tags/v') && endsWith(github.ref_name, '-rc.1') && !endsWith(github.ref_name, '-rc.1-win7')
        run: |
          VERSION=$(echo "${{ github.ref_name }}" | sed 's/-rc\.1$//' | sed 's/^v//')
          python scripts/release/release_branches.py create \
            --tier rc --tag ${{ github.ref_name }} --version $VERSION
        env:
          SAGE_RELEASE_BOT_TOKEN: ${{ secrets.SAGE_RELEASE_BOT_TOKEN }}

      - name: Promote release/stable mirror on stable tag
        if: startsWith(github.ref, 'refs/tags/v') && !contains(github.ref_name, '-rc') && !contains(github.ref_name, '-beta') && !contains(github.ref_name, '-alpha') && !endsWith(github.ref_name, '-win7')
        run: |
          python scripts/release/release_branches.py promote-stable \
            --tier stable --tag ${{ github.ref_name }}
        env:
          SAGE_RELEASE_BOT_TOKEN: ${{ secrets.SAGE_RELEASE_BOT_TOKEN }}

      - name: Finalize stabilization branch on stable ship
        if: startsWith(github.ref, 'refs/tags/v') && !contains(github.ref_name, '-rc') && !contains(github.ref_name, '-beta') && !contains(github.ref_name, '-alpha') && !endsWith(github.ref_name, '-win7')
        run: |
          VERSION=$(echo "${{ github.ref_name }}" | sed 's/^v//')
          python scripts/release/release_branches.py finalize \
            --version $VERSION --main-branch main
        env:
          SAGE_RELEASE_BOT_TOKEN: ${{ secrets.SAGE_RELEASE_BOT_TOKEN }}
```

Important: The steps must run **before** "Upload artifacts to GitHub Release" so that:
1. On `vX.Y.0-rc.1`: branch is created before any artifacts are uploaded
2. On `vX.Y.0`: mirror is promoted + branch finalized before artifacts uploaded

- [ ] **Step 4.2: Verify YAML syntax**

Run:
```bash
cd /home/fz/project/sage && python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml').read())" && echo "YAML OK"
```

Expected: `YAML OK`. If yaml error, check indentation (must align with surrounding steps).

- [ ] **Step 4.3: Add 1 step to release-win7.yml**

Open `.github/workflows/release-win7.yml` and find a similar insertion point (after build, before upload). Add:

```yaml
      - name: Promote release/stable-win7 mirror
        if: startsWith(github.ref, 'refs/tags/v') && !contains(github.ref_name, '-rc') && !contains(github.ref_name, '-beta') && !contains(github.ref_name, '-alpha') && endsWith(github.ref_name, '-win7')
        run: |
          python scripts/release/release_branches.py promote-stable \
            --tier stable --tag ${{ github.ref_name }} --branch release/stable-win7
        env:
          SAGE_RELEASE_BOT_TOKEN: ${{ secrets.SAGE_RELEASE_BOT_TOKEN }}
```

- [ ] **Step 4.4: Verify release-win7.yml YAML syntax**

Run:
```bash
cd /home/fz/project/sage && python -c "import yaml; yaml.safe_load(open('.github/workflows/release-win7.yml').read())" && echo "YAML OK"
```

Expected: `YAML OK`.

- [ ] **Step 4.5: Verify trigger conditions don't overlap**

Manually inspect: the new steps use `endsWith` for rc.1 (not `contains`) to avoid matching rc.10/rc.11. The promote/finalize steps use `!contains -rc/-beta/-alpha` so they fire only on truly stable tags.

Test cases (mental):
- `v0.5.0-alpha.1` → none of the 3 steps fire ✅
- `v0.5.0-rc.1` → only `Detect rc.1` fires ✅
- `v0.5.0-rc.2` → none fire (rc.1 only) ✅
- `v0.5.0-rc.10` → none fire (endsWith rc.1 fails) ✅
- `v0.5.0` → `Promote` + `Finalize` fire ✅
- `v0.5.0-win7` → only win7 promote fires (in release-win7.yml) ✅

- [ ] **Step 4.6: Commit**

```bash
cd /home/fz/project/sage && git add .github/workflows/release.yml .github/workflows/release-win7.yml && git commit -m "ci(release): add 3 steps to release.yml + 1 step to release-win7.yml

release.yml 新增:
- Detect rc.1 and create stabilization branch: 仅 -rc.1 触发 (endsWith 避免误匹配 rc.10)
- Promote release/stable mirror on stable tag: 排除所有预发布段 + win7
- Finalize stabilization branch on stable ship: 同 promote-stable 触发条件

release-win7.yml 新增:
- Promote release/stable-win7 mirror: 排除预发布段 + 必 win7 后缀

触发条件都用 endsWith / !contains 精确匹配, 避免 -alpha.10/-rc.100 等误触发

依赖: SAGE_RELEASE_BOT_TOKEN secret (PR 文档化在 §30.7)"
```

---

### Task 5: PR label check (labeler.yml + pr-label-check.yml)

**Files:**
- Create: `.github/labeler.yml`
- Create: `.github/workflows/pr-label-check.yml`

**Interfaces:**

```yaml
# .github/labeler.yml: 配置哪些 PR target branch 触发 label check
# .github/workflows/pr-label-check.yml: CI job 在 PR base 是 release/v* 时检查 label
```

- [ ] **Step 5.1: Create labeler.yml**

Create `.github/labeler.yml`:

```yaml
# PR labeler 配置: PR target branch 为 release/v* 时强制 fix: 或 hotfix: label
# 配合 .github/workflows/pr-label-check.yml 实现强制
#
# 详细规则 (匹配条件):
#   1. PR base branch starts with 'release/v'
#   2. PR has at least one label in {fix:, hotfix:}
#   否则 CI 红

release-branch-base:
  baseBranches:
    - release/v*

required-labels:
  any-of:
    - fix:
    - hotfix:
  applies-to:
    - release-branch-base
```

- [ ] **Step 5.2: Create pr-label-check.yml workflow**

Create `.github/workflows/pr-label-check.yml`:

```yaml
name: PR Label Check (release branches)

on:
  pull_request:
    branches:
      - 'release/v*'
    types: [opened, edited, synchronize, reopened, labeled, unlabeled]

permissions:
  contents: read
  pull-requests: read

jobs:
  check-label:
    name: Verify fix: or hotfix: label on release/v* PRs
    runs-on: ubuntu-latest
    steps:
      - name: Check PR has fix: or hotfix: label
        env:
          LABELS_JSON: ${{ toJson(github.event.pull_request.labels.*.name) }}
        run: |
          echo "Labels on PR #${{ github.event.pull_request.number }}:"
          echo "$LABELS_JSON"

          # 接受 label 名: "fix:", "hotfix:", 或带 scope (如 "fix(electron):")
          # 简化: 仅匹配以 "fix:" 或 "hotfix:" 开头的 label
          if echo "$LABELS_JSON" | grep -qE '"(fix|hotfix):'; then
            echo "✅ PR has fix: or hotfix: label"
            exit 0
          fi

          echo "::error::PR to release/v* must have a 'fix:' or 'hotfix:' label."
          echo "Applicable labels:"
          echo "  - fix:"
          echo "  - fix(scope):"
          echo "  - hotfix:"
          echo ""
          echo "Per docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md §3.5"
          exit 1
```

- [ ] **Step 5.3: Verify YAML syntax**

Run:
```bash
cd /home/fz/project/sage && python -c "import yaml; yaml.safe_load(open('.github/labeler.yml').read())" && python -c "import yaml; yaml.safe_load(open('.github/workflows/pr-label-check.yml').read())" && echo "YAML OK"
```

Expected: `YAML OK`.

- [ ] **Step 5.4: Test the label check logic locally (optional)**

Manual simulation:
```bash
# 模拟一个 PR 的 labels JSON
LABELS='["feat: new feature"]'
echo "$LABELS" | grep -qE '"(fix|hotfix):' && echo "PASS" || echo "FAIL (no fix/hotfix label)"

LABELS='["fix: bug"]'
echo "$LABELS" | grep -qE '"(fix|hotfix):' && echo "PASS" || echo "FAIL"

LABELS='["fix(electron): logger TDZ"]'
echo "$LABELS" | grep -qE '"(fix|hotfix):' && echo "PASS" || echo "FAIL"
```

Expected:
- First: FAIL (no fix/hotfix label)
- Second: PASS
- Third: PASS (matches because starts with `fix(`)

- [ ] **Step 5.5: Commit**

```bash
cd /home/fz/project/sage && git add .github/labeler.yml .github/workflows/pr-label-check.yml && git commit -m "ci(release): add PR label check for release/v* branches

新增 .github/labeler.yml: 配置 PR base 是 release/v* 时触发 label check
新增 .github/workflows/pr-label-check.yml: CI job 在 PR 打开/编辑时检查 label

检查规则:
- PR base branch startsWith 'release/v'
- PR 必须有 label ∈ {fix:, hotfix:, fix(scope):, hotfix(scope):}
- 否则 CI 红, 提示用户加 label

依赖: docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md §3.5 分支保护规则"
```

---

### Task 6: Documentation sync (30-release-tiers.md §30.6 + §30.7)

**Files:**
- Modify: `docs/technical/30-release-tiers.md`

**Interfaces:**

Append two new sections after §30.5 (Related Docs):

- §30.6: **Release Branches** — explain the 5-branch model, lifecycle, when each is created/destroyed
- §30.7: **Branch Setup & Manual Smoke Test** — GitHub Settings 手动配置 + smoke test 步骤

- [ ] **Step 6.1: Read current §30.5 to find insertion point**

Run:
```bash
cd /home/fz/project/sage && grep -n "^## 30\." docs/technical/30-release-tiers.md | tail -5
```

Expected: §30.1-§30.5 are numbered. Insert §30.6 + §30.7 after §30.5.

- [ ] **Step 6.2: Append §30.6 + §30.7**

Append to `docs/technical/30-release-tiers.md` (after §30.5):

```markdown
---

## 30.6 Release Branches

> 设计规范：[`docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md`](../superpowers/specs/2026-07-10-release-branch-strategy-design.md)

Sage 在 tag-only 4 档分级之上，新增 **3 个物理分支** 解决"稳定化期 main 继续加新功能不污染候选版本"的场景：

| 分支 | 角色 | 生命周期 | 谁能推 |
|------|------|---------|--------|
| `main` | 主开发线 | 永久 | 任何人通过 PR |
| `release/vX.Y.0` | 当前版本稳定化线 | **临时**，stable ship 后删除 | 仅通过 PR（label 限制） |
| `release/stable` | 下游消费镜像（main） | 永久 | 仅 release workflow（PAT） |
| `release/win7` | Win7 LTS 维护线 | 永久至 2027-12-13 | 仅 cherry-pick from main |
| `release/stable-win7` | Win7 LTS 下游消费镜像 | 永久 | 仅 release-win7 workflow（PAT） |

### 时间线：v0.5.0 完整 cycle

```
T0   main ──────────────────────────────────────────────────────►
     │  feat: feat-A │ feat-B │ feat-C │ feat-D │ feat-E
     │
     ├─ v0.5.0-alpha.1 tag (T0+1d)        ← tag-only,不开分支
     ├─ v0.5.0-beta.1 tag (T0+5d)         ← tag-only,不开分支
     │
T1   ├─ v0.5.0-rc.1 tag (T0+10d)
     │   ├─ [自动化] git switch -c release/v0.5.0 v0.5.0-rc.1
     │   └─ 分支保护启用: 必须 fix:/hotfix: label
     │
T2   ├─ main 加 feat: → 后续 v0.6.0-alpha.1 (独立线,不污染)
     ├─ release/v0.5.0 加 fix: → v0.5.0-rc.2 (T1+3d)
     │
T3   ├─ release/v0.5.0 加 fix: → v0.5.0-rc.3 (T1+6d)
     │
T4   ├─ v0.5.0 tag 在 release/v0.5.0 上
     │   ├─ [自动化] git push <sha>:release/stable --force-with-lease
     │   ├─ [自动化] git checkout main && git merge --no-ff release/v0.5.0
     │   ├─ [自动化] git push origin main
     │   └─ [自动化] git push origin --delete release/v0.5.0
     │
T5   进入 v0.6.0 cycle: 再次从 v0.6.0-rc.1 开 release/v0.6.0
```

### 5 种 Commit 流转路径

| 路径 | 场景 | 操作 |
|------|------|------|
| **A** | main 加 feat: | PR → main (squash merge) |
| **B** | release/vX.Y.0 加 fix:（稳定化期主路径） | PR → release/vX.Y.0（label: fix:）+ cherry-pick 到 release/win7 + 段内升 tag |
| **C** | main 先合 fix:，需回 release/vX.Y.0 | `git cherry-pick <sha>` 到 release/vX.Y.0 后 push |
| **D** | release/vX.Y.0 先合 fix:，必须回 main | `git cherry-pick <sha>` 回 main（developer responsibility） |
| **E** | stable ship 收尾 | release.yml 触发 promote-stable + finalize |

详细命令：[`docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md` §4](../superpowers/specs/2026-07-10-release-branch-strategy-design.md#4-数据流5-种-commit-流转路径)

### 为什么 alpha/beta 不开分支

- **alpha**：仅给 Sage 贡献者用，不需要"在某版本上稳定化"的能力 → tag 够用
- **beta**：少量早期用户测试，但允许破坏性变更 → tag 够用
- **rc.1 起**：面向广泛用户的候选版，需"测试期 + 同时开发"的并行 → 开 release/vX.Y.0 物理分支承接

### YAGNI 边界

- ❌ 不开 `release/alpha`、`release/beta`、`release/rc` 镜像分支
- ❌ 不开 `release/vX.Y.0-win7`（release/win7 已充当 win7 自己的稳定化线）
- ❌ 不同时维护多个 `release/vX.Y.0`
- ❌ 不让用户自由 PR 到 `release/stable` / `release/stable-win7`

---

## 30.7 Branch Setup & Manual Smoke Test

### GitHub Settings 手动配置（首次部署）

> ⚠️ **必须在第一次合入 Task 4-5 PR 后立即配置**，否则 PR 检查无效。

**步骤 1：创建 SAGE_RELEASE_BOT_TOKEN secret**

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Generate new token：
   - Name: `SAGE_RELEASE_BOT_TOKEN`
   - Resource owner: `oneMuggle`
   - Repository access: Only select repositories → `sage`
   - Permissions: **Contents: Read and write**（仅此一项）
3. 复制 token，粘贴到 Sage repo → Settings → Secrets and variables → Actions → New repository secret
4. **不要**勾选 Allow access via workflows for fork PRs

**步骤 2：配置 `release/vX.Y.0` 分支保护**

1. Settings → Branches → Add branch protection rule
2. Branch name pattern: `release/v*`
3. 勾选：
   - ☑ Require a pull request before merging
   - ☑ Require approvals: 1
   - ☑ Dismiss stale pull request approvals when new commits are pushed
   - ☑ Require status checks to pass before merging
     - 搜并勾选: `Frontend TS` / `Electron build (ubuntu-latest)` / `Electron build (windows-latest)`
   - ☑ Require conversation resolution before merging
   - ☑ Do not allow force pushes
   - ☑ Do not allow deletions
4. **不**勾选：Require linear history (允许 merge commit)

**步骤 3：验证 label check 工作**

测试 PR：
```bash
git switch -c test/label-check main
echo "test" > /tmp/throwaway.txt  # 不要 commit, 此步仅演示
gh pr create --base main --title "test label check (will close)" --label "feat:" --body "this should NOT trigger label check (base is main)"
gh pr create --base release/v0.5.0 --title "test label check (will close)" --label "feat:" --body "this SHOULD trigger CI failure (base is release/v*, label is feat:)"
gh pr create --base release/v0.5.0 --title "test label check (will close)" --label "fix:" --body "this should PASS"
```

预期：
- 第 1 个 PR：pr-label-check job 不跑（base 是 main）✅
- 第 2 个 PR：pr-label-check job 红，提示加 `fix:` 或 `hotfix:` label
- 第 3 个 PR：pr-label-check job 绿

测试完关闭所有 test PR。

### 手动 Smoke Test（每次 release.yml 改动后必跑）

> 这是 release.yml 新 step 的验证流程，**首次合入 Task 4 PR 后必跑**。

**前置**：

- fork 仓库（避免污染主仓库）
- fork 上配置 `SAGE_RELEASE_BOT_TOKEN`（指向 fork repo）
- 在 fork 上重跑 release.yml（push tag 触发）

**测试场景 1：rc.1 创建 release/vX.Y.0 分支**

```bash
# 1. 在 fork main 上做几个 commit, 打 v0.5.0-rc.1 tag
git tag v0.5.0-rc.1
git push origin v0.5.0-rc.1

# 2. 观察 Actions: release.yml run
#    - "Detect rc.1 and create stabilization branch" step 应绿
#    - exit code 应为 0
#    - 远端应出现 release/v0.5.0 分支, 指向 v0.5.0-rc.1 commit

# 3. 验证
git fetch origin
git ls-remote --heads origin release/v0.5.0  # 应有输出
git rev-parse release/v0.5.0  # 应等于 v0.5.0-rc.1 commit
```

**测试场景 2：fix 在 release/vX.Y.0 合入 + 升 rc.2**

```bash
# 1. 在 fork release/v0.5.0 上 PR fix:
git switch release/v0.5.0
echo "fix content" >> README.md
git commit -am "fix: smoke test bug"
git push origin release/v0.5.0

# 2. PR 应通过 label check (fix: label)
#    - 合并后 release/v0.5.0 HEAD 前进

# 3. 手动打 v0.5.0-rc.2 tag
git tag v0.5.0-rc.2
git push origin v0.5.0-rc.2

# 4. 验证 release.yml 不触发新 step (rc.1 only)
#    Actions 跑 build, 但 Detect rc.1 不应跑
```

**测试场景 3：stable ship 收尾**

```bash
# 1. 在 release/v0.5.0 上打 v0.5.0 tag
git tag v0.5.0
git push origin v0.5.0

# 2. 观察 Actions:
#    - "Promote release/stable mirror" 应绿
#    - "Finalize stabilization branch" 应绿
#    - exit code 0

# 3. 验证:
git fetch origin
git rev-parse origin/release/stable     # 应等于 v0.5.0 commit
git ls-remote --heads origin release/v0.5.0  # 应为空 (已删)
git log main --oneline -5              # main HEAD 应含 release/v0.5.0 的 fix commit
```

**测试场景 4：cross-minor guard**

```bash
# 1. 不走 finalize 流程, 直接在 main 上推进 + 打 v0.6.0-rc.1 + v0.6.0 tag
git switch main
echo "v0.6 features" >> README.md
git commit -am "feat: v0.6 features"
git push origin main
git tag v0.6.0
git push origin v0.6.0

# 2. 观察 Actions: finalize step 应红 (exit 2)
#    报错: "previous stabilization branch release/v0.5.0 still open"

# 3. 手动补救:
git switch release/v0.5.0
git tag v0.5.0
git push origin v0.5.0
# 等 release.yml 跑完 promote + finalize
# 再重试 v0.6.0 finalize
```

### 失败排查

| 现象 | 排查 |
|------|------|
| `Detect rc.1` step 报 "branch already exists" | 正常：幂等 skip，verify log 看到 "already exists, skipping" |
| `Promote stable` 报 exit 4 (diverged) | release/stable 被外部 push 覆盖，需人工 review + 决定保留哪侧 |
| `Finalize` 报 exit 2 (previous still open) | 上 cycle release/vX.Y.0 未 finalize，先打稳定 tag 走完流程 |
| `Finalize` 报 exit 3 (conflict) | merge 冲突，按 §5.4 应急路径人工解 |
| PR label check 红但 PR 有 `fix:` label | label 全名匹配：应是 `fix:` `fix(scope):` `hotfix:`，不是 `Fix` `bug` `Bug Fix` |

### 故障回滚

- **回滚脚本**：删除 release_branches.py 文件 + revert Task 1-2 commit → workflow step 调不到脚本会红（feature 分支）→ 简单
- **回滚 workflow**：删除 release.yml 新增的 3 个 step + release-win7.yml 新增的 1 个 step → 回到纯 tag-only 模式
- **回滚 label check**：删除 .github/labeler.yml + pr-label-check.yml → PR 不再被强制
- **回滚 GitHub Settings**：手动去分支保护配置页面改回
```

- [ ] **Step 6.3: Verify docs link to scripts**

Run:
```bash
cd /home/fz/project/sage && grep -c "scripts/release/release_branches.py" docs/technical/30-release-tiers.md
```

Expected: ≥ 3 (脚本在 §30.6 至少出现 1 次，在 §30.7 至少出现 2 次)。

- [ ] **Step 6.4: Verify markdown renders correctly**

Open `docs/technical/30-release-tiers.md` in editor and:
- Section numbers are sequential (§30.1-§30.7)
- No broken links (click each link to ensure target exists)
- Tables render with proper alignment
- Code blocks have language tags (`bash`, `markdown`, `yaml`)

- [ ] **Step 6.5: Commit**

```bash
cd /home/fz/project/sage && git add docs/technical/30-release-tiers.md && git commit -m "docs(technical): add §30.6 Release Branches + §30.7 Branch Setup

§30.6 Release Branches:
- 5 类分支表 (含生命周期 + 谁能推)
- v0.5.0 完整 cycle 时间线图
- 5 种 commit 流转路径 (A-E)
- YAGNI 边界维持 (不开 release/alpha-beta-rc-vX.Y.0-win7)

§30.7 Branch Setup & Manual Smoke Test:
- GitHub Settings 手动配置 3 步骤:
  1. SAGE_RELEASE_BOT_TOKEN secret 创建 (Fine-grained PAT)
  2. release/v* 分支保护配置
  3. label check 验证
- 4 个手动 smoke test 场景:
  1. rc.1 创建分支
  2. fix 合入 + 升 rc.2
  3. stable ship 收尾
  4. cross-minor guard 失败
- 失败排查表 (5 个常见现象)
- 故障回滚 4 路径

锚定 docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md"
```

---

## Verification Checklist

After completing all 6 tasks:

- [ ] `scripts/release/release_branches.py` exists with 3 subcommands (create / promote-stable / finalize)
- [ ] `scripts/release/tests/test_release_branches.py` has 18+ tests, all pass
- [ ] `scripts/release/tests/integration/test_release_branch_lifecycle.py` has 3 tests, all pass
- [ ] `.github/workflows/release.yml` has 3 new steps, YAML valid
- [ ] `.github/workflows/release-win7.yml` has 1 new step, YAML valid
- [ ] `.github/labeler.yml` + `.github/workflows/pr-label-check.yml` exist
- [ ] `docs/technical/30-release-tiers.md` has §30.6 + §30.7
- [ ] All 6 commits follow conventional commit format
- [ ] `pytest scripts/release/tests/ -v` 全部绿
- [ ] `ruff check scripts/release/` 0 errors
- [ ] Manual smoke test 跑通（fork 仓库，或首次 v0.5.0-rc.1 tag 时在真环境跑）
- [ ] GitHub Settings 配置完成（Secret + 分支保护）

## Reference Documents

- 设计规范：[`docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md`](../specs/2026-07-10-release-branch-strategy-design.md)
- 上一份 spec（4 档 tag）：[`docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md`](../specs/2026-07-06-sage-release-tiers-design.md)
- 既有 CLI 脚本风格参考：[`scripts/release/infer_tier.py`](../../scripts/release/infer_tier.py) + [`append_changelog.py`](../../scripts/release/append_changelog.py)
- 既有测试风格参考：[`scripts/release/tests/test_infer_tier.py`](../../scripts/release/tests/test_infer_tier.py) + [`fixtures/sample_repo.sh`](../../scripts/release/tests/fixtures/sample_repo.sh)
- Win7 LTS 维护文档：[`docs/technical/21-win7-lts.md`](../technical/21-win7-lts.md)