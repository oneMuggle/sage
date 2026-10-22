"""``_write_resource_file()`` 的 resolve-and-contain 复核单测。

``_ensure_real_directory()`` 逐段 lstat 拒绝 symlink / reparse point,
但 lstat 与后续 open 之间存在 TOCTOU 窗口 —— 中间目录若在窗口内被换成
symlink, open 会跟随它写到 skills_dir 之外。resolve-and-contain 复核把窗口
收窄: 解析后的父目录必须仍在 skills_dir 之内。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.skill_md import importer as importer_mod
from backend.skills.skill_md.importer import _write_resource_file

pytestmark = pytest.mark.unit


def test_resource_write_rejected_when_parent_escapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中间目录被换成 symlink → resolve 复核发现越界 → 拒绝写入。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    # 模拟 TOCTOU: lstat 逐段检查全部通过, 但随后目录被换成 symlink。
    monkeypatch.setattr(importer_mod, "_ensure_real_directory", lambda _p: None)

    scripts = skills_dir / "scripts"
    scripts.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        _write_resource_file(skills_dir, Path("scripts/scan.py"), b"payload")

    assert not (outside / "scan.py").exists()


def test_resource_write_allowed_inside_skills_dir(tmp_path: Path) -> None:
    """正常路径(无 symlink)→ 写入成功。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    _write_resource_file(skills_dir, Path("scripts/scan.py"), b"payload")

    assert (skills_dir / "scripts" / "scan.py").read_bytes() == b"payload"
