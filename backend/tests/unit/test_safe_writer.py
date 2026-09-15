"""安全技能写入器的跨平台安全契约测试。

R32 起 Windows 分支由原生 reparse-safe 原语（win_reparse_io）实现：
本文件在 Windows 上直接验证端到端行为；symlink 相关用例做能力探测
（无特权环境自动 skip，CI windows runner 有特权可跑）。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.skills.safe_writer import write_skill_file


@pytest.mark.skipi()f(
    os.name == "nt",
    reason="POSIX 分支（目录 fd + O_NOFOLLOW）用例；Windows 分支见下方 R32 用例",
)
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


@pytest.mark.skipi()f(
    os.name == "nt",
    reason="POSIX 分支用例",
)
def test_non_overwrite_keeps_existing_file_unchanged(tmp_path: Path) -> None:
    """普通安全路径上的非覆盖写入仍保持 FileExistsError 语义。"""
    root = tmp_path / "skills"
    target = root / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_skill_file(root, "demo", "replacement", overwrite=False)

    assert target.read_text(encoding="utf-8") == "original"


# ---------- R32: Windows 原生 reparse-safe 分支 ----------


@pytest.mark.skipi()f(os.name != "nt", reason="Windows 原生分支行为")
def test_windows_write_roundtrip(tmp_path: Path) -> None:
    """Windows 端到端：写盘成功、内容一致、返回词法路径。"""
    root = tmp_path / "skills"
    target = write_skill_file(root, "demo", "windows-content", overwrite=False)

    assert target == root / "demo" / "SKILL.md"
    assert target.read_text(encoding="utf-8") == "windows-content"


@pytest.mark.skipi()f(os.name != "nt", reason="Windows 原生分支行为")
def test_windows_overwrite_truncates(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    first = write_skill_file(root, "demo", "longer-original", overwrite=False)
    write_skill_file(root, "demo", "short", overwrite=True)
    assert first.read_text(encoding="utf-8") == "short"


@pytest.mark.skipi()f(os.name != "nt", reason="Windows 原生分支行为")
def test_windows_non_overwrite_keeps_existing(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill_file(root, "demo", "original", overwrite=False)

    with pytest.raises(FileExistsError):
        write_skill_file(root, "demo", "replacement", overwrite=False)

    assert (root / "demo" / "SKILL.md").read_text(encoding="utf-8") == "original"


@pytest.mark.skipi()f(os.name != "nt", reason="Windows 原生分支行为")
def test_windows_rejects_path_separator_in_name(tmp_path: Path) -> None:
    """name 含分隔符 = 越界尝试，直接拒绝（越界防护契约）。"""
    root = tmp_path / "skills"
    root.mkdir()
    with pytest.raises(OSError, match="Refusing skill write outside"):
        write_skill_file(root, "demo/SKILL.md", "evil", overwrite=False)
    with pytest.raises(OSError, match="Refusing skill write outside"):
        write_skill_file(root, "..", "evil", overwrite=False)
    assert not (root / "SKILL.md").exists()


@pytest.mark.skipi()f(os.name != "nt", reason="Windows 原生分支行为")
def test_windows_rejects_symlinked_component(tmp_path: Path) -> None:
    """symlink 组件（目录或叶）必须被拒绝，秘密不得写入链接目标。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "skills"
    root.mkdir()
    link = root / "demo"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported")

    with pytest.raises(OSError, match="refusing|Refusing"):
        write_skill_file(root, "demo", "secret", overwrite=False)

    assert not (outside / "SKILL.md").exists()
