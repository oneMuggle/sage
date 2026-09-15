"""Tests for artifact version history (Phase 2 M2)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.data import artifact_repo


@pytest.fixture()
def tmp_artifact(tmp_path: Path):
    """Create a temp artifact with a real file on disk.

    Uses the autouse ``setup_test_db`` fixture from conftest — the temp DB
    is already initialized with the artifacts table schema.
    """
    content_file = tmp_path / "test.md"
    content_file.write_text("# Hello\n\nWorld\n", encoding="utf-8")

    artifact_id = artifact_repo.record_artifact(
        session_id="sess_1",
        path=str(content_file),
        name="test.md",
        kind="text",
        size=content_file.stat().st_size,
    )
    return artifact_id, content_file


def test_create_and_list_versions(tmp_artifact):
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    content = content_file.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    v1 = artifact_version_repo.create_version(
        artifact_id=artifact_id,
        content=content,
        content_hash=content_hash,
        snapshot_dir=str(content_file.parent / ".snapshots"),
        note="initial",
    )
    assert v1["version_num"] == 1
    assert v1["content_hash"] == content_hash

    v2 = artifact_version_repo.create_version(
        artifact_id=artifact_id,
        content="# Modified\n\nNew content\n",
        content_hash=hashlib.sha256(b"# Modified\n\nNew content\n").hexdigest(),
        snapshot_dir=str(content_file.parent / ".snapshots"),
        note="edit",
    )
    assert v2["version_num"] == 2

    versions = artifact_version_repo.list_versions(artifact_id)
    assert len(versions) == 2
    assert versions[0]["version_num"] == 2  # DESC order
    assert versions[1]["version_num"] == 1


def test_get_version_reads_snapshot(tmp_artifact):
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    content = content_file.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    snapshot_dir = str(content_file.parent / ".snapshots")

    artifact_version_repo.create_version(
        artifact_id=artifact_id,
        content=content,
        content_hash=content_hash,
        snapshot_dir=snapshot_dir,
        note="v1",
    )

    version = artifact_version_repo.get_version(artifact_id, 1)
    assert version is not None
    assert version["content"] == content
    assert version["content_hash"] == content_hash


def test_get_version_not_found(tmp_artifact):
    from backend.data import artifact_version_repo

    artifact_id, _ = tmp_artifact
    version = artifact_version_repo.get_version(artifact_id, 999)
    assert version is None


def test_get_latest_version(tmp_artifact):
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    snapshot_dir = str(content_file.parent / ".snapshots")
    content = content_file.read_text(encoding="utf-8")

    artifact_version_repo.create_version(
        artifact_id=artifact_id,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        snapshot_dir=snapshot_dir,
        note="v1",
    )
    artifact_version_repo.create_version(
        artifact_id=artifact_id,
        content="v2 content",
        content_hash=hashlib.sha256(b"v2 content").hexdigest(),
        snapshot_dir=snapshot_dir,
        note="v2",
    )

    latest = artifact_version_repo.get_latest_version(artifact_id)
    assert latest is not None
    assert latest["version_num"] == 2
    assert latest["content"] == "v2 content"


def test_list_versions_empty(tmp_artifact):
    from backend.data import artifact_version_repo

    artifact_id, _ = tmp_artifact
    versions = artifact_version_repo.list_versions(artifact_id)
    assert versions == []


def test_snapshot_file_created(tmp_artifact):
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    content = content_file.read_text(encoding="utf-8")
    snapshot_dir = str(content_file.parent / ".snapshots")

    artifact_version_repo.create_version(
        artifact_id=artifact_id,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        snapshot_dir=snapshot_dir,
        note="v1",
    )

    snapshot_path = Path(snapshot_dir) / f"{artifact_id}_v1.txt"
    assert snapshot_path.is_file()
    assert snapshot_path.read_text(encoding="utf-8") == content


def test_max_versions_enforced(tmp_artifact):
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    snapshot_dir = str(content_file.parent / ".snapshots")

    # Create 101 versions (max is 100)
    for i in range(101):
        content = f"version {i}"
        try:
            artifact_version_repo.create_version(
                artifact_id=artifact_id,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                snapshot_dir=snapshot_dir,
                note=f"v{i}",
            )
        except ValueError as e:
            assert "100" in str(e)
            # The 101st should fail
            assert i == 100
            break
    else:
        pytest.fail("Expected ValueError on 101st version")

    versions = artifact_version_repo.list_versions(artifact_id)
    assert len(versions) == 100


# ==================== apply_edit (Phase 2 M2) ====================


def test_apply_edit_success(tmp_artifact):
    """apply_edit: base_hash 匹配 → 文件替换 + 新版本创建。"""
    import asyncio
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    original = content_file.read_text(encoding="utf-8")
    base_hash = hashlib.sha256(original.encode()).hexdigest()

    new_content = "# Edited\n\nNew body\n"
    result = asyncio.get_event_loop().run_until_complete(
        artifact_version_repo.apply_edit(
            artifact_id=artifact_id,
            artifact_path=str(content_file),
            base_hash=base_hash,
            new_content=new_content,
            note="test edit",
        )
    )

    assert result["version_num"] == 1
    assert result["note"] == "test edit"
    # 文件内容已更新
    assert content_file.read_text(encoding="utf-8") == new_content
    # 快照存在
    snapshot = Path(content_file.parent / ".snapshots") / f"{artifact_id}_v1.txt"
    assert snapshot.read_text(encoding="utf-8") == new_content


def test_apply_edit_conflict(tmp_artifact):
    """apply_edit: base_hash 不匹配 → ConflictError。"""
    import asyncio
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    wrong_hash = "a" * 64  # SHA-256 hex 长度

    with pytest.raises(artifact_version_repo.ConflictError):
        asyncio.get_event_loop().run_until_complete(
            artifact_version_repo.apply_edit(
                artifact_id=artifact_id,
                artifact_path=str(content_file),
                base_hash=wrong_hash,
                new_content="# Should not be written\n",
            )
        )
    # 文件未被修改
    assert content_file.read_text(encoding="utf-8") == "# Hello\n\nWorld\n"


def test_apply_edit_content_too_large(tmp_artifact):
    """apply_edit: 超过 1 MiB → ValueError。"""
    import asyncio
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    original = content_file.read_text(encoding="utf-8")
    base_hash = hashlib.sha256(original.encode()).hexdigest()
    huge = "x" * (1024 * 1024 + 1)

    with pytest.raises(ValueError, match="1 MiB"):
        asyncio.get_event_loop().run_until_complete(
            artifact_version_repo.apply_edit(
                artifact_id=artifact_id,
                artifact_path=str(content_file),
                base_hash=base_hash,
                new_content=huge,
            )
        )


def test_apply_edit_missing_file(tmp_artifact):
    """apply_edit: 文件不存在 → FileNotFoundError。"""
    import asyncio
    from backend.data import artifact_version_repo

    artifact_id, content_file = tmp_artifact
    content_file.unlink()

    with pytest.raises(FileNotFoundError):
        asyncio.get_event_loop().run_until_complete(
            artifact_version_repo.apply_edit(
                artifact_id=artifact_id,
                artifact_path=str(content_file),
                base_hash="a" * 64,
                new_content="nope",
            )
        )
