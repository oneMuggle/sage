"""安全技能写入器的跨平台安全契约测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills import safe_writer
from backend.skills.safe_writer import write_skill_file


def test_windows_writer_fails_closed_when_no_follow_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不能证明 Windows 路径不会跟随 reparse point 时不得普通路径写入。"""
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(safe_writer.os, "name", "nt")
    monkeypatch.delattr(safe_writer.os, "O_NOFOLLOW", raising=False)

    with pytest.raises(OSError, match="fail-closed|reparse|no-follow"):
        write_skill_file(root, "demo", "content", overwrite=False)

    assert not (root / "demo" / "SKILL.md").exists()


def test_windows_writer_rejects_reparse_or_symlink_path_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows 分支不应把 lstat 检查当作可证明的 TOCTOU 防护。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "skills"
    root.mkdir()
    link = root / "demo"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported")

    monkeypatch.setattr(safe_writer.os, "name", "nt")
    with pytest.raises(OSError, match="Refusing skill write"):
        write_skill_file(root, "demo", "secret", overwrite=False)

    assert not (outside / "SKILL.md").exists()




def test_overwrite_rejects_hardlink_without_modifying_outside(tmp_path: Path) -> None:
    """POSIX overwrite must not truncate an inode linked outside the skills root."""
    root = tmp_path / "skills"
    target_dir = root / "demo"
    target_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside-secret", encoding="utf-8")
    target = target_dir / "SKILL.md"
    try:
        target.hardlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("hardlinks are not supported")

    with pytest.raises(OSError, match="private|regular"):
        write_skill_file(root, "demo", "replacement", overwrite=True)
    assert outside.read_text(encoding="utf-8") == "outside-secret"


def test_non_overwrite_keeps_existing_file_unchanged(tmp_path: Path) -> None:
    """普通安全路径上的非覆盖写入仍保持 FileExistsError 语义。"""
    root = tmp_path / "skills"
    target = root / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_skill_file(root, "demo", "replacement", overwrite=False)

    assert target.read_text(encoding="utf-8") == "original"
