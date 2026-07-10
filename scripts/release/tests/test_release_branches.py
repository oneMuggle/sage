"""Tests for release_branches.py — Sage release branch lifecycle manager.

Covers create / promote-stable / finalize subcommands with subprocess mocks.
"""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

RELEASE_BRANCHES = Path(__file__).parent.parent / "release_branches.py"

# Allow `from release_branches import main` to work when pytest runs from
# the project root (default rootdir adds the test file's directory's parent,
# not scripts/release/ itself).
sys.path.insert(0, str(RELEASE_BRANCHES.parent))


def _run(*args):
    """Helper to invoke release_branches.py with given CLI args."""
    return subprocess.run(
        [sys.executable, str(RELEASE_BRANCHES), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
    )


class TestTagFormat:
    """§3.1 error code 6: tag must match vX.Y.Z[-tier.N[-win7]]."""

    def test_valid_tag_alpha(self):
        result = _run("create", "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0")
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


class TestCreateSubcommand:
    """§3.1 create: idempotent, validates version matches tag."""

    @patch("subprocess.run")
    def test_create_calls_git_branch_with_correct_args(self, mock_run):
        # Arrange: mock git to succeed
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Act
        from release_branches import main
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
        assert "abc123def456:refs/heads/release/stable" in " ".join(push_args)
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
    def test_promote_force_lease_diverged_returns_4(self, mock_run, capsys):
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
        captured = capsys.readouterr()
        assert "diverged" in captured.err or "declined" in captured.err

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
        assert "win7sha:refs/heads/release/stable-win7" in " ".join(push_args)


class TestFinalize:
    """§3.1 finalize: merge release/vX.Y.0 back to main and delete."""

    @patch("subprocess.run")
    def test_finalize_merges_to_main_and_deletes_branch(self, mock_run):
        # 调用序列: fetch + ls-remote current + ls-remote previous + checkout + merge + push main + push delete
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # git fetch origin main
            MagicMock(returncode=0, stdout="sha\trefs/heads/release/v0.5.0\n", stderr=""),  # ls-remote current
            MagicMock(returncode=0, stdout="", stderr=""),  # ls-remote previous (v0.4.0 absent)
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
            MagicMock(returncode=0, stdout="sha\trefs/heads/release/v0.5.0\n", stderr=""),  # ls-remote current
            MagicMock(returncode=0, stdout="", stderr=""),  # ls-remote previous (absent)
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
    def test_finalize_refuses_when_previous_cycle_still_open(self, mock_run, capsys):
        """finalize v0.6.0 时 release/v0.5.0 仍存在 → exit 2."""
        # mock: ls-remote current 返回 v0.6.0 存在, ls-remote previous 返回 v0.5.0 残留
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # fetch
            MagicMock(returncode=0, stdout="sha\trefs/heads/release/v0.6.0\n", stderr=""),  # ls-remote current
            MagicMock(returncode=0, stdout="sha\trefs/heads/release/v0.5.0\n", stderr=""),  # ls-remote previous
        ]

        from release_branches import main
        with patch("sys.argv", ["release_branches.py", "finalize",
                                 "--version", "0.6.0",
                                 "--main-branch", "main"]):
            rc = main()

        assert rc == 2
        captured = capsys.readouterr()
        assert "previous stabilization branch" in captured.err or "previous" in captured.err