"""T-4a 技能目录 preference 单测。

覆盖 ``backend/skills/skill_md/skills_dir_policy.py`` 的读取与校验口径，
以及 ``SkillMdImporter._resolve_skills_dir()`` 的优先级链：

    显式参数 > SAGE_SKILLS_DIR env > preference "skills_dir" > ~/.sage/skills
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.importer import SkillMdImporter
from backend.skills.skill_md.skills_dir_policy import (
    SETTINGS_KEY_SKILLS_DIR,
    read_skills_dir_preference,
)


class _FakeRepo:
    """最小 SettingsRepository 替身。"""

    def __init__(self, value):
        self._value = value

    def get(self, key):
        assert key == SETTINGS_KEY_SKILLS_DIR
        return self._value


class _BrokenRepo:
    """读取即抛异常的 repo（模拟 DB 故障）。"""

    def get(self, key):
        raise RuntimeError("database is locked")


# ==================== preference 读取口径 ====================


def test_key_matches_settings_repository_whitelist():
    """目录 key 必须落在 SettingsRepository.KEYS 白名单里，否则后端返回 400。"""
    from backend.data.settings_repo import SettingsRepository

    assert SETTINGS_KEY_SKILLS_DIR in SettingsRepository.KEYS


def test_missing_value_is_none():
    """key 不存在 → None（调用方回退下一级）。"""
    assert read_skills_dir_preference(_FakeRepo(None)) is None


def test_empty_value_is_none():
    """空字符串 → None。"""
    assert read_skills_dir_preference(_FakeRepo("")) is None


@pytest.mark.parametrize("value", [123, ["skills"], {"skills_dir": "skills"}])
def test_non_string_value_falls_back(value: object):
    """损坏的非字符串 preference → None，不把 TypeError 升级成启动失败。"""
    assert read_skills_dir_preference(_FakeRepo(value)) is None


def test_absolute_path_is_returned(tmp_path: Path):
    """宿主原生绝对路径 → 原样返回（不做 mkdir，交给调用方）。"""
    skills_dir = tmp_path / "skills"

    assert read_skills_dir_preference(_FakeRepo(str(skills_dir))) == skills_dir
    assert not skills_dir.exists()


def test_absolute_path_with_posix_separators_is_returned(tmp_path: Path):
    """宿主原生绝对路径的正斜杠表示仍按宿主路径解析。"""
    skills_dir = tmp_path / "skills"

    assert read_skills_dir_preference(_FakeRepo(skills_dir.as_posix())) == skills_dir


def test_user_home_is_expanded():
    """``~`` 开头的路径展开为绝对路径。"""
    result = read_skills_dir_preference(_FakeRepo("~/my-skills"))
    assert result is not None
    assert result.is_absolute()
    assert result == Path.home() / "my-skills"


def test_relative_path_is_rejected():
    """相对路径 → None（回退下一级），避免按 CWD 解析出意外目录。"""
    assert read_skills_dir_preference(_FakeRepo("relative/skills")) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows drive-relative 路径语义")
@pytest.mark.parametrize("value", ["/opt/skills", r"\opt\skills", "C:skills"])
def test_windows_partial_absolute_paths_are_rejected(value: str):
    """无盘符 root-relative / drive-relative 都依赖当前盘状态，必须回退。"""
    assert read_skills_dir_preference(_FakeRepo(value)) is None


def test_parent_traversal_is_rejected(tmp_path: Path):
    """含 ``..`` 段的路径 → None（路径穿越防御）。"""
    traversal = tmp_path / "skills" / ".." / "escape"

    assert read_skills_dir_preference(_FakeRepo(str(traversal))) is None


def test_repo_failure_falls_back():
    """DB 故障 → None，不得因无法读取把设置损坏升级成启动失败。"""
    assert read_skills_dir_preference(_BrokenRepo()) is None


# ==================== _resolve_skills_dir 优先级 ====================


@pytest.fixture()
def registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture()
def stub_preference(monkeypatch: pytest.MonkeyPatch):
    """把 importer 模块里的 preference 读取替换成可控 stub。"""

    def _install(value):
        monkeypatch.setattr(
            "backend.skills.skill_md.importer.read_skills_dir_preference",
            lambda: Path(value) if value else None,
        )

    return _install


def test_explicit_argument_wins_over_preference(
    registry: SkillRegistry, tmp_path: Path, stub_preference
):
    """显式参数优先级最高。"""
    explicit = tmp_path / "explicit"
    stub_preference(str(tmp_path / "preference"))

    resolved = SkillMdImporter(registry, skills_dir=explicit)._resolve_skills_dir()

    assert resolved == explicit


def test_env_wins_over_preference(
    registry: SkillRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_preference
):
    """SAGE_SKILLS_DIR env 压过 preference(env > DB preference, 与代码库约定一致)。"""
    env_dir = tmp_path / "env"
    pref_dir = tmp_path / "preference"
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(env_dir))
    stub_preference(str(pref_dir))

    resolved = SkillMdImporter(registry)._resolve_skills_dir()

    assert resolved == env_dir
    assert env_dir.is_dir()


def test_env_used_when_no_preference(
    registry: SkillRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_preference
):
    """无 preference 时回退 env var。"""
    env_dir = tmp_path / "env"
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(env_dir))
    stub_preference(None)

    resolved = SkillMdImporter(registry)._resolve_skills_dir()

    assert resolved == env_dir


def test_default_used_when_no_preference_and_no_env(
    registry: SkillRegistry, monkeypatch: pytest.MonkeyPatch, stub_preference
):
    """preference 与 env 都缺 → 缺省 ``~/.sage/skills``。"""
    monkeypatch.delenv("SAGE_SKILLS_DIR", raising=False)
    stub_preference(None)

    resolved = SkillMdImporter(registry)._resolve_skills_dir()

    assert resolved == Path.home() / ".sage" / "skills"
