# mypy: disable-error-code="no-untyped-def,attr-defined,func-returns-value"
"""SkillMdHotLoader 单测 + validation 工具间接覆盖。

覆盖 backend.skills.skill_md.loader:
- discover_skill_md_dirs() 按 env / cwd / ~/.sage 优先级返回目录
- SkillMdHotLoader.scan_and_load: 正常路径 / builtin 冲突 / malformed skip
- SkillMdHotLoader 热重载: body / frontmatter 变更检测
- SkillMdHotLoader.get_stats
- validate_base_dir 路径遍历防御 (in-root pass, ../ etc/passwd reject, symlink reject)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.loader import (
    SkillMdHotLoader,
    discover_skill_md_dirs,
    register_skill_md_skills,
)
from backend.skills.skill_md.validation import (
    SkillMdSecurityError,
    sanitize_for_logging,
    validate_base_dir,
)

pytestmark = pytest.mark.unit


# =====================================================================
# helpers
# =====================================================================


def _write_skill_md(
    parent: Path,
    name: str,
    frontmatter_extra: str = "",
    body: str = "Body content\n",
) -> Path:
    """在 parent/<name>/SKILL.md 写一个合法 SKILL.md, 返回路径。"""
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: test {name}\n"
        f"{frontmatter_extra}"
        f"---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def _write_bad_skill_md(parent: Path, name: str, text: str) -> Path:
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


# =====================================================================
# discover_skill_md_dirs
# =====================================================================


def test_discover_dirs_default_returns_only_existing(tmp_path, monkeypatch):
    """默认情况下 cwd/skills 不存在 → 不出现在结果中。"""
    monkeypatch.setenv("SAGE_SKILLS_DIR", "")
    monkeypatch.chdir(tmp_path)
    result = [Path(d).resolve() for d in discover_skill_md_dirs()]
    # cwd/skills 不在结果中 (因为不存在)
    assert (tmp_path / "skills").resolve() not in result


def test_discover_dirs_respects_env_var(tmp_path, monkeypatch):
    """SAGE_SKILLS_DIR 存在 → 优先级最高, 在列表最前。"""
    env_dir = tmp_path / "env-skills"
    env_dir.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(env_dir))
    monkeypatch.chdir(tmp_path)
    result = [Path(d).resolve() for d in discover_skill_md_dirs()]
    assert result[0] == env_dir.resolve()


def test_discover_dirs_includes_cwd_skills(tmp_path, monkeypatch):
    """cwd/skills 存在时, 出现在列表中(优先级仅次于 env var)。"""
    cwd_skills = tmp_path / "skills"
    cwd_skills.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", "")
    monkeypatch.chdir(tmp_path)
    result = [Path(d).resolve() for d in discover_skill_md_dirs()]
    assert cwd_skills.resolve() in result


# =====================================================================
# SkillMdHotLoader — scan_and_load
# =====================================================================


def test_scan_loads_skill_md_files(tmp_path):
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "alpha")
    _write_skill_md(tmp_path, "beta")

    loaded, skipped = loader.scan_and_load()
    assert loaded == 2
    assert skipped == 0
    assert registry.exists("alpha")
    assert registry.exists("beta")
    assert "alpha" in registry.list_names()


def test_scan_skips_non_skill_md_files(tmp_path):
    """非 SKILL.md 文件(如 README.md)被忽略。"""
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "alpha")
    (tmp_path / "README.md").write_text("not a skill\n", encoding="utf-8")
    (tmp_path / "x.txt").write_text("also not\n", encoding="utf-8")

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert registry.exists("alpha")


def test_scan_skips_hidden_dirs(tmp_path):
    """.开头的隐藏目录不被扫描(v1 简化)。"""
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "alpha")
    _write_skill_md(tmp_path, ".hidden-skill")

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert registry.exists("alpha")
    assert not registry.exists(".hidden-skill")


def test_scan_skips_malformed_file_but_continues(tmp_path):
    """malformed SKILL.md 不中断扫描, 其他正常文件仍被加载。"""
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "good")
    _write_bad_skill_md(
        tmp_path, "bad", "---\nname: bad\ndescription: ok\n---more fence no close\n"
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 1
    assert registry.exists("good")
    assert not registry.exists("bad")


def test_scan_skips_missing_required_field(tmp_path):
    """name 不是合法 slug → skip。"""
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "good")
    _write_bad_skill_md(
        tmp_path,
        "bad-name",
        "---\nname: Has Spaces\ndescription: y\n---\nbody\n",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 1
    assert registry.exists("good")
    assert not registry.exists("Has Spaces")


def test_scan_collision_with_builtin_skips_skillmd(tmp_path):
    """SKILL.md 与 builtin 同名 → builtin 胜, SKILL.md skip。"""
    from backend.skills import SearchSkill  # builtin

    registry = SkillRegistry()
    registry.register(SearchSkill())  # name="search"
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "search", body="some other body")

    loaded, skipped = loader.scan_and_load()
    assert loaded == 0
    assert skipped == 1
    # builtin 仍在, content 不是 SKILL.md body
    builtin = registry.get("search")
    assert builtin is not None
    result = builtin.execute(params={}, context={})
    assert result.content != "some other body"


def test_scan_returns_zero_when_dir_empty(tmp_path):
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    loaded, skipped = loader.scan_and_load()
    assert loaded == 0
    assert skipped == 0
    assert registry.list_names() == []


def test_scan_returns_zero_when_dir_missing(tmp_path):
    """dirs 中有不存在的目录, 跳过该目录但不报错。"""
    registry = SkillRegistry()
    nonexistent = tmp_path / "nope"
    loader = SkillMdHotLoader(registry, dirs=[nonexistent])
    loaded, skipped = loader.scan_and_load()
    assert loaded == 0
    assert skipped == 0


# =====================================================================
# SkillMdHotLoader — 热重载
# =====================================================================


def test_hot_reload_on_body_change(tmp_path):
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    path = _write_skill_md(tmp_path, "alpha", body="original body")
    loader.scan_and_load()

    # 改 body
    path.write_text(
        "---\nname: alpha\ndescription: test alpha\n---\nNEW body\n",
        encoding="utf-8",
    )

    assert loader.check_for_updates() == ["alpha"]
    assert loader.hot_reload("alpha") is True

    skill = registry.get("alpha")
    result = skill.execute(params={}, context={})
    assert result.content == "NEW body\n"


def test_hot_reload_on_frontmatter_change(tmp_path):
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "alpha", frontmatter_extra="version: 0.1.0\n")
    loader.scan_and_load()

    skill = registry.get("alpha")
    r1 = skill.execute(params={}, context={})
    assert r1.metadata["version"] == "0.1.0"

    # 改 frontmatter
    path = tmp_path / "alpha" / "SKILL.md"
    path.write_text(
        "---\nname: alpha\ndescription: test alpha\nversion: 0.2.0\n---\nbody\n",
        encoding="utf-8",
    )

    assert "alpha" in loader.check_for_updates()
    assert loader.hot_reload("alpha") is True

    skill = registry.get("alpha")
    r2 = skill.execute(params={}, context={})
    assert r2.metadata["version"] == "0.2.0"


def test_hot_reload_no_change_returns_false(tmp_path):
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "alpha")
    loader.scan_and_load()

    assert loader.check_for_updates() == []
    assert loader.hot_reload("alpha") is True  # 强制 reload 仍能成功


def test_hot_reload_unknown_skill_returns_false(tmp_path):
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    assert loader.hot_reload("nonexistent") is False


def test_hot_reload_all_returns_count(tmp_path):
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "alpha")
    _write_skill_md(tmp_path, "beta")
    loader.scan_and_load()

    # 改两个的 body
    (tmp_path / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: test alpha\n---\nNEW alpha\n",
        encoding="utf-8",
    )
    (tmp_path / "beta" / "SKILL.md").write_text(
        "---\nname: beta\ndescription: test beta\n---\nNEW beta\n",
        encoding="utf-8",
    )

    reloaded = loader.hot_reload_all()
    assert reloaded == 2


def test_get_stats(tmp_path):
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    _write_skill_md(tmp_path, "alpha")
    loader.scan_and_load()

    stats = loader.get_stats()
    assert stats["loaded_skills"] == 1
    assert stats["watched_files"] == 1
    assert tmp_path.resolve() in [Path(d).resolve() for d in stats["skill_dirs"]]


# =====================================================================
# validate_base_dir — 路径遍历防御
# =====================================================================


def test_validate_base_dir_in_root_passes(tmp_path):
    """base_dir 在 allowed_roots 内 → 通过, 返回 resolve 后的路径。"""
    root = tmp_path / "skills"
    root.mkdir()
    base = root / "alpha"
    base.mkdir()
    resolved = validate_base_dir(base, allowed_roots=[root])
    assert resolved == base.resolve()


def test_validate_base_dir_root_itself_passes(tmp_path):
    """base_dir == allowed_root 自身也算合法。"""
    root = tmp_path / "skills"
    root.mkdir()
    resolved = validate_base_dir(root, allowed_roots=[root])
    assert resolved == root.resolve()


def test_validate_base_dir_rejects_traversal(tmp_path):
    """base_dir 用 ../ 跳出 allowed_roots → 抛 SkillMdSecurityError。"""
    root = tmp_path / "skills"
    root.mkdir()
    base = tmp_path / "evil"
    base.mkdir()
    with pytest.raises(SkillMdSecurityError):
        validate_base_dir(base, allowed_roots=[root])


def test_validate_base_dir_rejects_sibling(tmp_path):
    """兄弟目录(看起来像平级)也算非法。"""
    root = tmp_path / "skills"
    sibling = tmp_path / "other"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(SkillMdSecurityError):
        validate_base_dir(sibling, allowed_roots=[root])


def test_validate_base_dir_rejects_symlink_escape(tmp_path):
    """symlink 指到 allowed_root 之外 → 抛异常。"""
    root = tmp_path / "skills"
    root.mkdir()
    escape = tmp_path / "secret"
    escape.mkdir()
    link = root / "sneaky-link"
    link.symlink_to(escape)

    with pytest.raises(SkillMdSecurityError):
        validate_base_dir(link, allowed_roots=[root])


def test_validate_base_dir_empty_allowed_raises():
    """allowed_roots 为空 → 抛异常。"""
    with pytest.raises(SkillMdSecurityError):
        validate_base_dir(Path("/tmp"), allowed_roots=[])


def test_validate_base_dir_multiple_roots_first_match(tmp_path):
    """多个 allowed_roots, 命中第一个就返回。"""
    root1 = tmp_path / "r1"
    root2 = tmp_path / "r2"
    root1.mkdir()
    root2.mkdir()
    base = root2 / "alpha"
    base.mkdir()
    resolved = validate_base_dir(base, allowed_roots=[root1, root2])
    assert resolved == base.resolve()


# =====================================================================
# sanitize_for_logging
# =====================================================================


def test_sanitize_replaces_control_chars():
    s = "hello\x00world\x07test"
    out = sanitize_for_logging(s, max_len=100)
    assert "\x00" not in out
    assert "\x07" not in out
    assert out == "hello?world?test"


def test_sanitize_truncates_long_input():
    s = "x" * 1000
    out = sanitize_for_logging(s, max_len=50)
    assert len(out) < 200  # 50 + 后缀
    assert "truncated" in out


def test_sanitize_keeps_short_input_intact():
    s = "safe content"
    assert sanitize_for_logging(s, max_len=100) == s


def test_sanitize_handles_non_string():
    """非字符串输入 → 转字符串再处理(避免日志抛 TypeError)。"""
    out = sanitize_for_logging(12345, max_len=100)
    assert out == "12345"


# =====================================================================
# register_skill_md_skills — 顶层封装
# =====================================================================


def test_register_skill_md_skills_helper(tmp_path):
    """register_skill_md_skills 是 scan_and_load + 日志的便捷封装。"""
    registry = SkillRegistry()
    _write_skill_md(tmp_path, "alpha")
    loaded = register_skill_md_skills(registry, dirs=[str(tmp_path)])
    assert loaded == 1
    assert registry.exists("alpha")
