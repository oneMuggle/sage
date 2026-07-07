# mypy: disable-error-code="no-untyped-def,attr-defined,func-returns-value"
"""验证 ``backend.tools.skill.SkillHotLoader`` 主要行为。

覆盖：
- 构造（默认 skill_dirs / 自定义 skill_dirs / 目录不存在时自动创建 __init__.py）
- ``scan_and_load`` 正常路径：返回新加载数量，技能被注册到 registry
- ``scan_and_load`` 跳过 ``__init__.py`` / 隐藏文件 / 非 .py 文件
- ``_load_from_file`` 文件不存在 / spec 缺失时返回 False
- ``_load_from_file`` 文件中含非 BaseSkill / BaseSkill 子类时的混合处理
- ``_load_from_file`` 实例化失败时打 ERROR 日志且不影响其他 skill
- ``check_for_updates`` 检测 hash 变更
- ``hot_reload`` 成功路径与失败路径
- ``hot_reload_all`` 调用 ``check_for_updates`` + 循环 ``hot_reload``
- ``get_stats`` 输出字段
- ``_compute_hash`` 一致性
"""

from __future__ import annotations
from typing import List

import os
import textwrap
from pathlib import Path

import pytest

from backend.skills.registry import SkillRegistry
from backend.tools.skill import SkillHotLoader

pytestmark = pytest.mark.unit


# ============================================================================
# helpers
# ============================================================================


def _write_skill_file(path: Path, class_name: str) -> None:
    """写一个最小 skill .py 文件到 ``path``。"""
    schema_name = class_name.lower()
    path.write_text(
        textwrap.dedent(
            f"""\
            from backend.skills.base import BaseSkill, SkillResult, SkillSchema

            class {class_name}(BaseSkill):
                def _build_schema(self):
                    return SkillSchema(
                        name="{schema_name}",
                        description="{class_name}",
                        triggers=["{schema_name}"],
                    )

                def execute(self, params, context):
                    return SkillResult(content="ok")
            """
        ),
        encoding="utf-8",
    )


def _write_invalid_skill_file(path: Path) -> None:
    """写一个 import 失败的 skill 文件（用于触发异常路径）。"""
    path.write_text("raise RuntimeError('boom on import')\n", encoding="utf-8")


# ============================================================================
# 构造
# ============================================================================


def test_default_skill_dirs_uses_builtin(tmp_path, monkeypatch) -> None:
    """不传 skill_dirs 时默认指向 backend/skills/builtin。"""
    # 不让 _ensure_dirs 真的去创建 builtin
    monkeypatch.setattr("os.makedirs", lambda *a, **kw: None)
    monkeypatch.setattr("os.path.exists", lambda _p: True)
    # 直接构造，skill_dirs 应指向 builtin 目录
    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg)
    assert loader.registry is reg
    assert len(loader._skill_dirs) == 1
    assert loader._skill_dirs[0].endswith("skills/builtin")
    # _file_hashes / _loaded_skills 初始为空
    assert loader._file_hashes == {}
    assert loader._loaded_skills == {}


def test_custom_skill_dirs_creates_init_file(tmp_path) -> None:
    """自定义 skill_dirs 时若不存在则创建目录与 __init__.py。"""
    target = tmp_path / "skills"
    # 先确保父目录不存在
    assert not target.exists()

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(target)])

    # 构造时 _ensure_dirs 已运行
    assert target.is_dir()
    init_file = target / "__init__.py"
    assert init_file.is_file()
    assert "Skills directory" in init_file.read_text(encoding="utf-8")
    assert loader._skill_dirs == [str(target)]


def test_ensure_dirs_skips_init_creation_when_exists(tmp_path) -> None:
    """__init__.py 已存在时不应覆盖。"""
    target = tmp_path / "skills"
    target.mkdir()
    init_file = target / "__init__.py"
    init_file.write_text("# existing\n", encoding="utf-8")

    reg = SkillRegistry()
    SkillHotLoader(registry=reg, skill_dirs=[str(target)])

    assert init_file.read_text(encoding="utf-8") == "# existing\n"


def test_ensure_dirs_called_on_every_skill_dir(tmp_path, monkeypatch) -> None:
    """_ensure_dirs 应在构造时对每个 skill_dir 调用 makedirs。"""
    dirs = [str(tmp_path / f"d{i}") for i in range(3)]
    called: List[str] = []
    real_makedirs = os.makedirs
    monkeypatch.setattr(
        "os.makedirs",
        lambda p, *a, **kw: (called.append(str(p)), real_makedirs(p, *a, **kw))[1],
    )
    SkillHotLoader(registry=SkillRegistry(), skill_dirs=dirs)
    assert called == dirs


# ============================================================================
# scan_and_load + _load_from_file
# ============================================================================


def test_scan_and_load_loads_skill_files(tmp_path) -> None:
    """正常路径：扫描目录，调用 _load_from_file，registry 注册所有 skill。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill_file(skills_dir / "alpha.py", "AlphaSkill")
    _write_skill_file(skills_dir / "beta.py", "BetaSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])

    n = loader.scan_and_load()

    assert n == 2
    assert reg.exists("alphaskill")
    assert reg.exists("betaskill")
    # _loaded_skills / _file_hashes 都被填充
    assert set(loader._loaded_skills.keys()) == {"alphaskill", "betaskill"}
    assert len(loader._file_hashes) == 2


def test_scan_and_load_skips_init_and_hidden_and_non_py(tmp_path) -> None:
    """__init__.py / 隐藏文件 / 非 .py 文件都应被跳过。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "__init__.py").write_text("# marker\n", encoding="utf-8")
    (skills_dir / ".hidden.py").write_text("# hidden\n", encoding="utf-8")
    (skills_dir / "README.md").write_text("not python\n", encoding="utf-8")
    _write_skill_file(skills_dir / "ok.py", "OkSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])

    n = loader.scan_and_load()

    assert n == 1
    assert reg.exists("okskill")
    # __init__.py 内容没有被覆盖
    assert (skills_dir / "__init__.py").read_text(encoding="utf-8") == "# marker\n"


def test_scan_and_load_silently_skips_missing_directory(tmp_path) -> None:
    """skill_dir 不存在时该目录被跳过，不抛错。"""
    existing = tmp_path / "skills"
    existing.mkdir()
    missing = tmp_path / "ghost"  # 不创建
    _write_skill_file(existing / "alive.py", "AliveSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(missing), str(existing)])

    n = loader.scan_and_load()
    assert n == 1
    assert reg.exists("aliveskill")


def test_scan_and_load_returns_zero_when_no_files(tmp_path) -> None:
    """目录为空时返回 0。"""
    skills_dir = tmp_path / "empty_skills"
    skills_dir.mkdir()

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])

    assert loader.scan_and_load() == 0
    assert reg.list_names() == []


def test_load_from_file_returns_false_for_invalid_skill_file(tmp_path) -> None:
    """文件中没有 BaseSkill 子类时返回 False。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    bad = skills_dir / "noskill.py"
    bad.write_text("x = 1\n", encoding="utf-8")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])

    assert loader._load_from_file(str(bad)) is False
    assert reg.list_names() == []


def test_load_from_file_returns_false_for_missing_path(tmp_path, caplog) -> None:
    """路径不存在时 _load_from_file 返回 False 并打 ERROR 日志。"""
    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(tmp_path)])

    fake = str(tmp_path / "no_such_file.py")
    with caplog.at_level("ERROR", logger="backend.tools.skill"):
        assert loader._load_from_file(fake) is False
    assert any("加载 Skill 文件失败" in r.message for r in caplog.records)


def test_load_from_file_logs_error_on_import_failure(tmp_path, caplog) -> None:
    """模块 import 失败时 _load_from_file 走外层 except → ERROR 日志、found=False。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_invalid_skill_file(skills_dir / "boom.py")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])

    with caplog.at_level("ERROR", logger="backend.tools.skill"):
        result = loader.scan_and_load()

    assert result == 0
    assert reg.list_names() == []
    assert any("加载 Skill 文件失败" in r.message for r in caplog.records)


def test_load_from_file_continues_after_one_skill_raises(tmp_path, caplog) -> None:
    """一个 class 实例化抛异常，不影响同文件其它 class。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    mixed = skills_dir / "mixed.py"
    mixed.write_text(
        textwrap.dedent(
            """\
            from backend.skills.base import BaseSkill, SkillResult, SkillSchema

            class GoodSkill(BaseSkill):
                def _build_schema(self):
                    return SkillSchema(
                        name="good",
                        description="good",
                        triggers=["good"],
                    )
                def execute(self, params, context):
                    return SkillResult(content="ok")

            class BrokenSkill(BaseSkill):
                def __init__(self):
                    raise RuntimeError("nope")
                def _build_schema(self):
                    return SkillSchema(name="broken", description="b", triggers=["b"])
                def execute(self, params, context):
                    return SkillResult(content="ok")
            """
        ),
        encoding="utf-8",
    )

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])

    with caplog.at_level("ERROR", logger="backend.tools.skill"):
        n = loader.scan_and_load()

    # GoodSkill 注册成功，BrokenSkill 实例化失败 → 文件整体 found=True
    assert n == 1
    assert reg.exists("good")
    assert not reg.exists("broken")
    assert any("实例化 Skill 失败" in r.message for r in caplog.records)


def test_load_from_file_ignores_non_class_objects(tmp_path) -> None:
    """模块里只有函数 / 变量 / BaseSkill 自身时不应注册。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    mixed = skills_dir / "misc.py"
    mixed.write_text(
        textwrap.dedent(
            """\
            from backend.skills.base import BaseSkill

            def helper():
                return 1

            SOMETHING = "x"

            # BaseSkill 自身不是它的有效子类
            class _(BaseSkill):
                pass
            """
        ),
        encoding="utf-8",
    )

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])

    assert loader.scan_and_load() == 0
    assert reg.list_names() == []


# ============================================================================
# check_for_updates / hot_reload / hot_reload_all
# ============================================================================


def test_check_for_updates_returns_empty_when_no_changes(tmp_path) -> None:
    """无变更时返回空列表。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill_file(skills_dir / "stable.py", "StableSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])
    loader.scan_and_load()

    assert loader.check_for_updates() == []


def test_check_for_updates_detects_file_change(tmp_path) -> None:
    """文件内容变更时返回受影响的 skill 名。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    target = skills_dir / "changeable.py"
    _write_skill_file(target, "ChangeableSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])
    loader.scan_and_load()
    initial_hash = loader._file_hashes[str(target)]

    # 修改文件内容
    target.write_text(target.read_text(encoding="utf-8") + "\n# tweak\n", encoding="utf-8")
    new_hash = loader._compute_hash(str(target))
    assert new_hash != initial_hash

    updates = loader.check_for_updates()
    assert "changeableskill" in updates


def test_check_for_updates_skips_vanished_files(tmp_path) -> None:
    """文件被删除时该项被静默跳过，不抛错。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    target = skills_dir / "temp.py"
    _write_skill_file(target, "TempSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])
    loader.scan_and_load()

    target.unlink()
    # 不抛错，返回空列表
    assert loader.check_for_updates() == []


def test_hot_reload_returns_false_for_unknown_skill() -> None:
    """未注册 skill 时 hot_reload 返回 False。"""
    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg)
    assert loader.hot_reload("ghost") is False


def test_hot_reload_returns_false_when_file_missing(tmp_path) -> None:
    """skill 在 registry 但对应文件已删除 → 返回 False, registry 中旧实例保留。

    注意: 源码在 file_path 不存在时直接 return False, 不会 unregister.
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    target = skills_dir / "doomed.py"
    _write_skill_file(target, "DoomedSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])
    loader.scan_and_load()
    target.unlink()

    assert loader.hot_reload("doomedskill") is False
    # 早返回不会触发 unregister: 旧实例仍存在
    assert reg.exists("doomedskill")


def test_hot_reload_success_updates_hash(tmp_path) -> None:
    """热重载成功：unregister 旧实例 → 重新加载 → 更新 hash。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    target = skills_dir / "rl.py"
    _write_skill_file(target, "RlSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])
    loader.scan_and_load()
    old_hash = loader._file_hashes[str(target)]

    # 修改文件让 hash 改变
    target.write_text(target.read_text(encoding="utf-8") + "\n# new\n", encoding="utf-8")

    assert loader.hot_reload("rlskill") is True
    # 新的 hash 与 _compute_hash 一致
    new_hash = loader._compute_hash(str(target))
    assert loader._file_hashes[str(target)] == new_hash
    assert loader._file_hashes[str(target)] != old_hash
    # registry 仍有该 skill（被新实例替换）
    assert reg.exists("rlskill")


def test_hot_reload_failure_when_file_no_longer_a_skill(tmp_path) -> None:
    """热重载时文件变成不含 BaseSkill → 返回 False。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    target = skills_dir / "rl2.py"
    _write_skill_file(target, "Rl2Skill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])
    loader.scan_and_load()

    # 把 skill 文件改坏（无 BaseSkill）
    target.write_text("x = 42\n", encoding="utf-8")

    # hot_reload 调用 _load_from_file 返回 False → hot_reload 返回 False
    assert loader.hot_reload("rl2skill") is False
    # 旧实例已被 unregister
    assert not reg.exists("rl2skill")


def test_hot_reload_all_reloads_changed_skills(tmp_path) -> None:
    """hot_reload_all 调用 check_for_updates + 循环 hot_reload。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    a = skills_dir / "a.py"
    b = skills_dir / "b.py"
    _write_skill_file(a, "ASkill")
    _write_skill_file(b, "BSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])
    loader.scan_and_load()

    # 改 a，b 不动
    a.write_text(a.read_text(encoding="utf-8") + "\n# t\n", encoding="utf-8")

    reloaded = loader.hot_reload_all()
    assert reloaded == 1
    # 两个 skill 都还在 registry（a 重新注册过）
    assert reg.exists("askill")
    assert reg.exists("bskill")


# ============================================================================
# get_stats / _compute_hash
# ============================================================================


def test_get_stats_returns_expected_fields(tmp_path) -> None:
    """get_stats 输出 loaded_skills / watched_files / skill_dirs。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill_file(skills_dir / "one.py", "OneSkill")

    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg, skill_dirs=[str(skills_dir)])
    loader.scan_and_load()

    stats = loader.get_stats()
    assert stats["loaded_skills"] == 1
    assert stats["watched_files"] == 1
    assert stats["skill_dirs"] == [str(skills_dir)]


def test_get_stats_empty_loader() -> None:
    """空 loader 统计字段为 0 / []."""
    reg = SkillRegistry()
    loader = SkillHotLoader(registry=reg)
    stats = loader.get_stats()
    assert stats["loaded_skills"] == 0
    assert stats["watched_files"] == 0
    # 默认 skill_dirs 至少 1 项
    assert len(stats["skill_dirs"]) == 1


def test_compute_hash_is_deterministic_and_md5(tmp_path) -> None:
    """_compute_hash 对相同内容返回相同值且为 32 位 hex。"""
    p = tmp_path / "f.txt"
    p.write_text("hello world", encoding="utf-8")
    h1 = SkillHotLoader._compute_hash(str(p))
    h2 = SkillHotLoader._compute_hash(str(p))
    assert h1 == h2
    assert len(h1) == 32
    # 内容变更后 hash 变化
    p.write_text("hello world!", encoding="utf-8")
    assert SkillHotLoader._compute_hash(str(p)) != h1


def test_compute_hash_different_files_different_hashes(tmp_path) -> None:
    """不同文件应得到不同 hash。"""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("alpha", encoding="utf-8")
    b.write_text("beta", encoding="utf-8")
    assert SkillHotLoader._compute_hash(str(a)) != SkillHotLoader._compute_hash(str(b))
