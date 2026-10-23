"""``discover_skill_md_dirs()`` 与 ``skills_dir`` preference 的优先级单测。

背景: 导入端 ``_resolve_skills_dir()`` 把技能**写**到用户配置的 ``skills_dir``,
加载端必须扫到同一处 —— 否则自定义目录里的技能在重启后"消失"。
本文件锁定加载端口径: env > preference > cwd > ~/.sage/skills。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.skill_md import loader as skill_md_loader
from backend.skills.skill_md.loader import discover_skill_md_dirs

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _stub_preference(monkeypatch):
    """默认屏蔽 preference, 避免真实 DB 的自定义目录影响断言。"""
    monkeypatch.setattr(
        skill_md_loader, "read_skills_dir_preference", lambda *a, **k: None
    )


def test_env_dir_is_first(tmp_path, monkeypatch):
    """SAGE_SKILLS_DIR env 存在 → 排在列表最前(与 _resolve_skills_dir 写入口径一致)。"""
    env_dir = tmp_path / "env-skills"
    env_dir.mkdir()
    pref_dir = tmp_path / "custom-skills"
    pref_dir.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(env_dir))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        skill_md_loader, "read_skills_dir_preference", lambda *a, **k: pref_dir
    )
    result = [Path(d).resolve() for d in discover_skill_md_dirs()]
    assert result[0] == env_dir.resolve()


def test_env_outranks_preference(tmp_path, monkeypatch):
    """SAGE_SKILLS_DIR env 优先于 preference(与 _resolve_skills_dir 写入口径一致)。"""
    pref_dir = tmp_path / "custom-skills"
    pref_dir.mkdir()
    env_dir = tmp_path / "env-skills"
    env_dir.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(env_dir))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        skill_md_loader, "read_skills_dir_preference", lambda *a, **k: pref_dir
    )
    result = [Path(d).resolve() for d in discover_skill_md_dirs()]
    assert result[0] == env_dir.resolve()
    assert pref_dir.resolve() in result


def test_missing_preference_dir_is_filtered(tmp_path, monkeypatch):
    """preference 指向不存在的目录 → 过滤掉, 不抛错。"""
    missing = tmp_path / "nope"
    monkeypatch.setenv("SAGE_SKILLS_DIR", "")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        skill_md_loader, "read_skills_dir_preference", lambda *a, **k: missing
    )
    result = [Path(d).resolve() for d in discover_skill_md_dirs()]
    assert missing.resolve() not in result


def test_preference_read_failure_falls_back(tmp_path, monkeypatch):
    """preference 读取抛异常 → 静默回退, 目录发现绝不因设置损坏而失败。"""

    def _boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setenv("SAGE_SKILLS_DIR", "")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(skill_md_loader, "read_skills_dir_preference", _boom)
    result = [Path(d).resolve() for d in discover_skill_md_dirs()]
    assert (tmp_path / "skills").resolve() not in result
