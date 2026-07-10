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