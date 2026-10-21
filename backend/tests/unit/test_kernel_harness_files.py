# ruff: noqa: UP006, UP035
"""R84 harness file set: lock、snapshot、diff、rollback 与启动 gate。"""

import json
import os
from typing import List

import pytest

from backend.application.kernel.harness_config import (
    HarnessConfigError,
    clear_harness_cache,
    load_harness_config,
)
from backend.application.kernel.harness_files import (
    HarnessFilesError,
    HarnessFileSpec,
    assert_adopted_harness_files_valid,
    load_harness_lock,
    normalize_harness_path,
    update_harness_lock,
    verify_harness_files,
)
from backend.application.kernel.harness_snapshots import (
    create_harness_snapshot,
    harness_diff_view,
    harness_status_view,
    list_harness_snapshots,
    rollback_harness_files,
    write_harness_files,
)

FIXED_TIME = "2026-10-21T00:00:00Z"


def _specs(system_text: str = "be helpful\n") -> List[HarnessFileSpec]:
    return [
        HarnessFileSpec(
            "system.md",
            system_text,
            component="system",
            provenance="test:system",
            owner="sage-builtin",
        ),
        HarnessFileSpec(
            "plugins.yaml",
            "harness_config:\n  preset: standard\n",
            component="plugins",
            provenance="test:plugins",
            owner="sage-builtin",
            authority="configuration",
        ),
        HarnessFileSpec(
            "skills/demo/SKILL.md",
            "# Demo\n",
            component="skills",
            provenance="test:skill",
            owner="workspace",
        ),
    ]


def _codes(root):
    return {issue.code for issue in verify_harness_files(root).issues}


def test_write_creates_valid_lock_and_initial_snapshot(tmp_path):
    root = tmp_path / "harness"

    result = write_harness_files(root, _specs(), generated_at=FIXED_TIME)

    verification = verify_harness_files(root)
    lock = load_harness_lock(root)
    assert result["file_count"] == 3
    assert verification.valid is True
    assert verification.adopted is True
    assert verification.counts == {
        "unchanged": 3,
        "modified": 0,
        "missing": 0,
        "added": 0,
    }
    assert lock is not None
    assert lock.generated_at == FIXED_TIME
    assert lock.startup_enforced is True
    assert lock.by_path["system.md"].provenance == "test:system"
    assert [item.snapshot_id for item in list_harness_snapshots(root)] == ["initial"]


def test_verify_reports_modified_missing_added_and_reserved_areas(tmp_path):
    root = tmp_path / "harness"
    write_harness_files(root, _specs(), generated_at=FIXED_TIME)

    (root / "proposals").mkdir()
    (root / "proposals" / "future.md").write_text("R85 area\n", encoding="utf-8")
    assert verify_harness_files(root).valid is True

    (root / "system.md").write_text("be helpful!\n", encoding="utf-8")
    (root / "skills" / "demo" / "SKILL.md").unlink()
    (root / "extra.md").write_text("untracked\n", encoding="utf-8")

    verification = verify_harness_files(root)
    assert verification.valid is False
    assert verification.counts == {
        "unchanged": 1,
        "modified": 1,
        "missing": 1,
        "added": 1,
    }
    assert {"size_mismatch", "missing_file", "untracked_file"} <= {
        issue.code for issue in verification.issues
    }
    status = harness_status_view(root)
    assert status["missing_files"] == ["skills/demo/SKILL.md"]


def test_lock_content_hash_and_update_lock_preserve_metadata(tmp_path):
    root = tmp_path / "harness"
    write_harness_files(
        root,
        _specs(),
        generated_at=FIXED_TIME,
        startup_enforced=False,
    )
    lock_path = root / "harness.lock.json"
    raw = json.loads(lock_path.read_text(encoding="utf-8"))
    raw["content_sha256"] = "0" * 64
    lock_path.write_text(json.dumps(raw), encoding="utf-8")
    assert "lock_content_hash_mismatch" in _codes(root)

    (root / "system.md").write_text("reviewed change\n", encoding="utf-8")
    lock = update_harness_lock(root, generated_at="2026-10-21T01:00:00Z")

    assert verify_harness_files(root).valid is True
    assert lock.startup_enforced is False
    assert lock.by_path["system.md"].provenance == "test:system"


def test_diff_and_rollback_restore_every_managed_file(tmp_path):
    root = tmp_path / "harness"
    write_harness_files(root, _specs(), generated_at=FIXED_TIME)

    (root / "system.md").write_text("be careful\n", encoding="utf-8")
    (root / "skills" / "demo" / "SKILL.md").unlink()
    (root / "new.md").write_text("new\n", encoding="utf-8")

    diff = harness_diff_view(root, include_patch=True)
    by_path = {entry["path"]: entry for entry in diff["entries"]}
    assert diff["counts"] == {
        "added": 1,
        "modified": 1,
        "deleted": 1,
        "unchanged": 1,
    }
    assert by_path["system.md"]["status"] == "modified"
    assert "--- a/system.md" in by_path["system.md"]["patch"]
    assert by_path["skills/demo/SKILL.md"]["status"] == "deleted"
    assert by_path["new.md"]["status"] == "added"

    result = rollback_harness_files(root, "initial")
    assert result["restored_files"] == 3
    assert result["pre_snapshot"] is not None
    assert (root / "system.md").read_text(encoding="utf-8") == "be helpful\n"
    assert (root / "skills" / "demo" / "SKILL.md").exists()
    assert not (root / "new.md").exists()
    assert verify_harness_files(root).valid is True


def test_corrupt_snapshot_rollback_does_not_mutate_current_files(tmp_path):
    root = tmp_path / "harness"
    write_harness_files(root, _specs(), generated_at=FIXED_TIME)
    (root / "system.md").write_text("current\n", encoding="utf-8")
    snapshot_file = root / ".snapshots" / "initial" / "files" / "system.md"
    snapshot_file.write_text("tampered snapshot\n", encoding="utf-8")

    with pytest.raises(HarnessFilesError, match="hash mismatch"):
        rollback_harness_files(root, "initial")

    assert (root / "system.md").read_text(encoding="utf-8") == "current\n"


def test_path_safety_and_snapshot_id_validation(tmp_path):
    for unsafe in ("../outside.md", "a/../../b.md", "/abs.md", "C:/abs.md"):
        with pytest.raises(HarnessFilesError):
            normalize_harness_path(unsafe)

    root = tmp_path / "harness"
    write_harness_files(root, _specs(), generated_at=FIXED_TIME)
    with pytest.raises(HarnessFilesError, match="invalid snapshot id"):
        create_harness_snapshot(root, "../escape")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_symlink_is_rejected(tmp_path):
    root = tmp_path / "harness"
    write_harness_files(root, _specs(), generated_at=FIXED_TIME)
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    target = root / "system.md"
    target.unlink()
    try:
        os.symlink(str(outside), str(target))
    except OSError as exc:
        pytest.skip(f"cannot create symlink: {exc}")

    assert "symlink_rejected" in _codes(root)


def test_startup_gate_no_lock_noop_and_invalid_lock_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    user_home = tmp_path / "home"
    workspace.mkdir()
    user_home.mkdir()

    assert (
        assert_adopted_harness_files_valid(
            workspace=workspace,
            user_home=user_home,
            environ={},
        )
        == []
    )

    root = workspace / "harness"
    write_harness_files(root, _specs(), generated_at=FIXED_TIME)
    assert len(
        assert_adopted_harness_files_valid(
            workspace=workspace,
            user_home=user_home,
            environ={},
        )
    ) == 1

    (root / "system.md").write_text("drift\n", encoding="utf-8")
    with pytest.raises(HarnessFilesError, match="refusing to start"):
        assert_adopted_harness_files_valid(
            workspace=workspace,
            user_home=user_home,
            environ={},
        )

    assert (
        assert_adopted_harness_files_valid(
            workspace=workspace,
            user_home=user_home,
            environ={"SAGE_HARNESS_LOCK_ENFORCE": "0"},
        )
        == []
    )


def test_startup_gate_respects_inspection_only_lock(tmp_path):
    workspace = tmp_path / "workspace"
    user_home = tmp_path / "home"
    root = workspace / "harness"
    write_harness_files(
        root,
        _specs(),
        generated_at=FIXED_TIME,
        startup_enforced=False,
    )
    (root / "system.md").write_text("drift\n", encoding="utf-8")

    results = assert_adopted_harness_files_valid(
        workspace=workspace,
        user_home=user_home,
        environ={},
    )
    assert len(results) == 1
    assert results[0].valid is False
    assert results[0].enforced is False


def test_plugins_yaml_layer_requires_valid_lock(tmp_path):
    workspace = tmp_path / "workspace"
    user_home = tmp_path / "home"
    root = workspace / "harness"
    specs = _specs()
    specs[1] = HarnessFileSpec(
        "plugins.yaml",
        "harness_config:\n  preset: focus\n",
        component="plugins",
        provenance="test:plugins",
        authority="configuration",
    )
    write_harness_files(root, specs, generated_at=FIXED_TIME)
    clear_harness_cache()

    config = load_harness_config(
        workspace=workspace,
        user_home=user_home,
        environ={},
        known_bundles=["core", "browser"],
    )
    assert config.preset == "focus"
    assert any(source.endswith("plugins.yaml") for source in config.sources)

    with open(root / "plugins.yaml", "a", encoding="utf-8") as handle:
        handle.write("# drift\n")
    clear_harness_cache()
    config = load_harness_config(
        workspace=workspace,
        user_home=user_home,
        environ={},
        known_bundles=["core", "browser"],
    )
    assert config.preset == "standard"
    assert any("lock" in warning for warning in config.warnings)

    with pytest.raises(HarnessConfigError, match="lock"):
        load_harness_config(
            workspace=workspace,
            user_home=user_home,
            environ={},
            known_bundles=["core", "browser"],
            strict=True,
        )
    clear_harness_cache()
