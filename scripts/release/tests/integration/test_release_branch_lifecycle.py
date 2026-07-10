"""Integration tests for release_branches.py.

Uses temporary local git repos (git init --bare + git clone) to verify
end-to-end release branch lifecycle without mocking. Mirrors the bash
fixture pattern from scripts/release/tests/fixtures/sample_repo.sh but
adds a bare remote + clone to simulate an origin/main workflow.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

RELEASE_BRANCHES = Path(__file__).parent.parent.parent / "release_branches.py"


@pytest.fixture
def git_remote(tmp_path):
    """Create bare 'origin' + local clone with main branch.

    Yields (origin_path, work_path). Cleanup is automatic via tmp_path;
    shutil.rmtree guards against CWD-shared failure modes.
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"

    # bare remote (default branch main)
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        check=True,
        capture_output=True,
    )

    # local clone
    subprocess.run(
        ["git", "clone", str(origin), str(work)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )

    # initial commit on main
    (work / "README.md").write_text("# init\n")
    subprocess.run(["git", "-C", str(work), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "chore: initial"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "-u", "origin", "main"],
        check=True, capture_output=True,
    )

    yield origin, work

    # Safety net cleanup (tmp_path is auto-cleaned by pytest but shutil.rmtree
    # defends against in-progress CWD clobber from prior test).
    shutil.rmtree(tmp_path, ignore_errors=True)


def _run(work: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke release_branches.py with given CLI args inside work tree."""
    return subprocess.run(
        ["/home/fz/anaconda3/envs/sage-backend/bin/python", str(RELEASE_BRANCHES), *args],
        cwd=str(work),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(work / ".home")},
    )


def _commit(work: Path, msg: str, file_content: str = "x") -> str:
    """Create commit with msg + file content; return SHA and push to origin/main."""
    (work / "data.txt").write_text(f"{msg}\n{file_content}\n")
    subprocess.run(["git", "-C", str(work), "add", "data.txt"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", msg],
        check=True, capture_output=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "main"],
        check=True, capture_output=True,
    )
    return sha


def test_full_lifecycle_rc_to_stable(git_remote):
    """Full cycle: tag rc.1 → release/vX.Y.0 created → fix on release → main
    diverges → stable tag → promote-stable → finalize (merge to main + delete)."""
    origin, work = git_remote

    # Phase 1: tag rc.1 + create release/v0.5.0 from it.
    # NOTE: create uses `git branch <name> <tag>`, so the tag MUST exist locally
    # before invoking create. The brief's "调整" comment calls this out: push
    # the tag first, then invoke create.
    _commit(work, "feat: add scheduler (M3)", "scheduler-v1")
    subprocess.run(
        ["git", "-C", str(work), "tag", "v0.5.0-rc.1"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "v0.5.0-rc.1"],
        check=True, capture_output=True,
    )
    rc1_result = _run(
        work, "create",
        "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0",
    )
    assert rc1_result.returncode == 0, f"create failed: {rc1_result.stderr}"

    # Phase 2: independent main-line commit (diverges from release).
    _commit(work, "feat: add welcome page (M6)", "welcome")

    # Phase 3: stabilization fix on release/v0.5.0.
    subprocess.run(["git", "-C", str(work), "fetch", "origin"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "checkout", "release/v0.5.0"],
        check=True, capture_output=True,
    )
    (work / "fix.txt").write_text("fix: scheduler crash on Windows\n")
    subprocess.run(["git", "-C", str(work), "add", "fix.txt"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "fix: scheduler crash on Windows"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "-u", "origin", "release/v0.5.0"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "tag", "v0.5.0-rc.2"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "v0.5.0-rc.2"],
        check=True, capture_output=True,
    )

    # Assert: main HEAD ≠ release/v0.5.0 HEAD (the two lines diverged).
    main_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    rel_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "release/v0.5.0"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert main_sha != rel_sha, (
        "main and release/v0.5.0 should diverge after independent commits"
    )

    # Phase 4: cut stable tag on release branch.
    subprocess.run(["git", "-C", str(work), "tag", "v0.5.0"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "v0.5.0"],
        check=True, capture_output=True,
    )

    # promote-stable → release/stable points at v0.5.0 commit.
    promote = _run(
        work, "promote-stable",
        "--tier", "stable", "--tag", "v0.5.0",
    )
    assert promote.returncode == 0, f"promote-stable failed: {promote.stderr}"

    # finalize → merge release/v0.5.0 to main, delete branch, skip cross-minor
    # guard (minor=0, no previous cycle to check).
    final = _run(
        work, "finalize",
        "--version", "0.5.0", "--main-branch", "main",
    )
    assert final.returncode == 0, f"finalize failed: {final.stderr}"

    # Assert: release/stable points at v0.5.0 commit on the remote.
    remote = origin.as_uri()
    stable_sha = subprocess.run(
        ["git", "ls-remote", "--heads", remote, "release/stable"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    v050_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "v0.5.0"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert v050_sha[:7] in stable_sha, (
        f"release/stable should point to v0.5.0 ({v050_sha[:7]}), got: {stable_sha}"
    )

    # Assert: release/v0.5.0 deleted on remote.
    ls = subprocess.run(
        ["git", "ls-remote", "--heads", remote, "release/v0.5.0"],
        capture_output=True, text=True,
    )
    assert not ls.stdout.strip(), (
        f"release/v0.5.0 should be deleted, but ls-remote found: {ls.stdout}"
    )

    # Assert: main contains the fix commit (cherry-picked during finalize merge).
    subprocess.run(
        ["git", "-C", str(work), "fetch", "origin"],
        check=True, capture_output=True,
    )
    main_log = subprocess.run(
        [
            "git", "-C", str(work), "log", "main",
            "--grep=fix: scheduler crash on Windows", "--oneline",
        ],
        check=True, capture_output=True, text=True,
    )
    assert "fix: scheduler crash on Windows" in main_log.stdout, (
        f"main should contain the fix commit after finalize, got: {main_log.stdout}"
    )


def test_cherry_pick_from_main_to_release_branch(git_remote):
    """Path C: fix lands on main first, cherry-pick to release/vX.Y.0."""
    origin, work = git_remote

    # Setup: create release/v0.5.0 from a tag.
    _commit(work, "feat: initial feature")
    subprocess.run(
        ["git", "-C", str(work), "tag", "v0.5.0-rc.1"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "v0.5.0-rc.1"],
        check=True, capture_output=True,
    )
    create_result = _run(
        work, "create",
        "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0",
    )
    assert create_result.returncode == 0, f"create failed: {create_result.stderr}"

    # Main-line fix lands after rc.1 cut.
    _commit(work, "fix: critical bug on main")

    # Path C: cherry-pick the main fix onto release/v0.5.0.
    fix_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(work), "fetch", "origin"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "checkout", "release/v0.5.0"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "cherry-pick", fix_sha],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "release/v0.5.0"],
        check=True, capture_output=True,
    )

    # Verify: release/v0.5.0 contains the fix commit (cherry-pick applied).
    rel_log = subprocess.run(
        ["git", "-C", str(work), "log", "release/v0.5.0", "--oneline"],
        check=True, capture_output=True, text=True,
    )
    assert "fix: critical bug on main" in rel_log.stdout, (
        f"release/v0.5.0 should contain 'fix: critical bug on main', got: {rel_log.stdout}"
    )


def test_cherry_pick_from_release_branch_to_main(git_remote):
    """Path D: fix lands on release/vX.Y.0 first, cherry-pick back to main."""
    origin, work = git_remote

    # Setup: create release/v0.5.0 from a tag.
    _commit(work, "feat: initial feature")
    subprocess.run(
        ["git", "-C", str(work), "tag", "v0.5.0-rc.1"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "v0.5.0-rc.1"],
        check=True, capture_output=True,
    )
    create_result = _run(
        work, "create",
        "--tier", "rc", "--tag", "v0.5.0-rc.1", "--version", "0.5.0",
    )
    assert create_result.returncode == 0, f"create failed: {create_result.stderr}"

    # Stabilization fix on release/v0.5.0.
    subprocess.run(
        ["git", "-C", str(work), "fetch", "origin"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "checkout", "release/v0.5.0"],
        check=True, capture_output=True,
    )
    (work / "fix.txt").write_text("fix on release branch")
    subprocess.run(["git", "-C", str(work), "add", "fix.txt"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "fix: bug found during stabilization"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "-u", "origin", "release/v0.5.0"],
        check=True, capture_output=True,
    )

    # Path D: cherry-pick the release-line fix back to main.
    fix_sha = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "release/v0.5.0"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(work), "checkout", "main"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "cherry-pick", fix_sha],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "main"],
        check=True, capture_output=True,
    )

    # Verify: main now contains the stabilization fix commit.
    main_log = subprocess.run(
        ["git", "-C", str(work), "log", "main", "--oneline"],
        check=True, capture_output=True, text=True,
    )
    assert "fix: bug found during stabilization" in main_log.stdout, (
        f"main should contain 'fix: bug found during stabilization', got: {main_log.stdout}"
    )
