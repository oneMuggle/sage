"""R157 — SkillLoader（SKILL.md 落盘器）单元测试。

覆盖：write 落盘与覆盖、name 非法字符防御（空/斜杠/点目录）、read
回读与缺失 None、skills_dir 三级解析优先级、全局单例 get/reset。
"""

from __future__ import annotations

import pytest

from backend.skills.loader import SkillLoader, get_skill_loader, reset_skill_loader

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate_skills_env(monkeypatch):
    """隔离 SAGE_SKILLS_DIR，防止单例/环境变量泄漏。"""
    monkeypatch.delenv("SAGE_SKILLS_DIR", raising=False)


# ---------------------------------------------------------------------------
# write / read
# ---------------------------------------------------------------------------


def test_write_creates_skill_file(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path / "skills")
    out = loader.write("my-skill", "---\nname: my-skill\n---\nbody")
    assert out == tmp_path / "skills" / "my-skill" / "SKILL.md"
    assert out.read_text(encoding="utf-8") == "---\nname: my-skill\n---\nbody"


def test_write_overwrites_existing_content(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path)
    loader.write("s", "v1", overwrite=True)
    loader.write("s", "v2", overwrite=True)
    assert (tmp_path / "s" / "SKILL.md").read_text(encoding="utf-8") == "v2"


@pytest.mark.parametrize("bad", ["", "a/b", "a\\b", ".", ".."])
def test_write_invalid_name_rejected(tmp_path, bad):
    loader = SkillLoader(skills_dir=tmp_path)
    with pytest.raises(ValueError, match="Invalid skill name"):
        loader.write(bad, "content")


def test_read_returns_content(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path / "skills")
    loader.write("s", "全文")
    assert loader.read("s") == "全文"


def test_read_missing_returns_none(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path / "skills")
    assert loader.read("nope") is None


@pytest.mark.parametrize("bad", ["", "a/b", ".."])
def test_read_invalid_name_rejected(tmp_path, bad):
    loader = SkillLoader(skills_dir=tmp_path)
    with pytest.raises(ValueError, match="Invalid skill name"):
        loader.read(bad)


# ---------------------------------------------------------------------------
# skills_dir 解析优先级
# ---------------------------------------------------------------------------


def test_explicit_dir_wins_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path / "from-env"))
    loader = SkillLoader(skills_dir=tmp_path / "explicit")
    loader.write("s", "c")
    assert (tmp_path / "explicit" / "s" / "SKILL.md").is_file()
    assert not (tmp_path / "from-env").exists()


def test_env_dir_used_when_no_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path / "env-skills"))
    loader = SkillLoader()
    loader.write("s", "c")
    assert (tmp_path / "env-skills" / "s" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------


def test_get_skill_loader_singleton():
    reset_skill_loader()
    assert get_skill_loader() is get_skill_loader()
    reset_skill_loader()
    assert get_skill_loader() is not None  # 重置后重建
    reset_skill_loader()
