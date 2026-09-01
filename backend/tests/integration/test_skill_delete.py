"""Integration tests for SkillMdDeleter + delete endpoint (Tasks 1-3).

覆盖 spec §"测试计划" (1) success (2) builtin block (3) 404 (4) invalid
name (5) outside skills_dir (6) registry unregister + Task 3 endpoint
200/400/404。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills import SkillRegistry, register_all_skills
from backend.skills.skill_md.delete import (
    BuiltinSkillError,
    SkillMdDeleter,
    SkillMdNotFoundError,
)

# Task 3 endpoint tests use the conftest ``client`` fixture + ``reset_skill_adapter``
# (见 ``backend/tests/conftest.py``),复用项目标准的 TestClient 装配模式 ——
# 不重复造 client fixture,确保与现有 skill 路由测试一致。

SAMPLE_SKILL_MD = """---
name: web-search
description: Search the web and return top results.
triggers:
  - search
  - search the web
---

# web-search skill body
"""


@pytest.fixture()
def tmp_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create SAGE_SKILLS_DIR with one SKILL.md skill."""
    skill_dir = tmp_path / "web-search"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def registry() -> SkillRegistry:
    """Fresh registry with builtin skills loaded."""
    reg = SkillRegistry()
    register_all_skills(reg)
    return reg


def test_delete_skill_md_succeeds(tmp_skills_dir: Path, registry: SkillRegistry) -> None:
    from backend.skills.skill_md.loader import register_skill_md_skills

    register_skill_md_skills(registry, dirs=[tmp_skills_dir])
    deleter = SkillMdDeleter(registry, skills_dir=tmp_skills_dir)

    result = deleter.delete("web-search")

    assert result["deleted"] is True
    assert result["name"] == "web-search"
    assert (tmp_skills_dir / "web-search").exists() is False


def test_delete_unregistered_directory_is_not_touched(tmp_path: Path, registry: SkillRegistry) -> None:
    target = tmp_path / "web-search"
    target.mkdir()
    (target / "sentinel.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(SkillMdNotFoundError):
        SkillMdDeleter(registry, skills_dir=tmp_path).delete("web-search")

    assert target.exists()
    assert (target / "sentinel.txt").exists()


def test_delete_uses_registered_base_dir_not_current_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: SkillRegistry
) -> None:
    from backend.skills.skill_md.loader import register_skill_md_skills

    registered_root = tmp_path / "registered"
    current_root = tmp_path / "current"
    for root in (registered_root, current_root):
        (root / "web-search").mkdir(parents=True)
        (root / "web-search" / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")
    register_skill_md_skills(registry, dirs=[registered_root])
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(current_root))

    SkillMdDeleter(registry, skills_dir=registered_root).delete("web-search")

    assert not (registered_root / "web-search").exists()
    assert (current_root / "web-search").exists()


def test_delete_single_file_skill_does_not_remove_skills_root(
    tmp_path: Path, registry: SkillRegistry
) -> None:
    from backend.skills.skill_md.loader import register_skill_md_skills

    (tmp_path / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")
    (tmp_path / "other.txt").write_text("keep", encoding="utf-8")
    register_skill_md_skills(registry, dirs=[tmp_path])

    result = SkillMdDeleter(registry, skills_dir=tmp_path).delete("web-search")

    assert result["deleted"] is True
    assert tmp_path.is_dir()
    assert not (tmp_path / "SKILL.md").exists()
    assert (tmp_path / "other.txt").exists()
    assert not registry.exists("web-search")


def test_delete_registered_symlink_is_blocked(tmp_path: Path, registry: SkillRegistry) -> None:
    from backend.skills.skill_md.skill import SkillMdDocument, SkillMdSkill

    real = tmp_path / "real"
    real.mkdir()
    (real / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")
    link = tmp_path / "web-search"
    link.symlink_to(real, target_is_directory=True)
    registry.register(
        SkillMdSkill(
            SkillMdDocument(
                name="web-search", description="search", body="body", base_dir=link
            )
        )
    )

    with pytest.raises(ValueError, match="symlink"):
        SkillMdDeleter(registry, skills_dir=tmp_path).delete("web-search")

    assert real.exists()
    assert link.is_symlink()


def test_inproc_delete_root_single_file_preserves_other_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: SkillRegistry
) -> None:
    """Inproc deletion must not rmtree the root for root-level SKILL.md."""
    from backend.adapters.out.skill.inproc import InprocSkillAdapter

    (tmp_path / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")
    other = tmp_path / "other-skill"
    other.mkdir()
    (other / "SKILL.md").write_text(
        SAMPLE_SKILL_MD.replace("web-search", "other-skill"), encoding="utf-8"
    )
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path))

    adapter = InprocSkillAdapter(registry=registry)
    result = adapter.delete_skill_md("web-search")

    assert result["deleted"] is True
    assert tmp_path.is_dir()
    assert not (tmp_path / "SKILL.md").exists()
    assert (other / "SKILL.md").exists()
    assert not adapter.has_skill("web-search")
    assert adapter.has_skill("other-skill")


def test_delete_filesystem_failure_keeps_registered_skill(
    tmp_skills_dir: Path, registry: SkillRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.skills.skill_md.loader import register_skill_md_skills

    register_skill_md_skills(registry, dirs=[tmp_skills_dir])
    monkeypatch.setattr(
        "backend.skills.skill_md.delete.shutil.rmtree",
        lambda _path: (_ for _ in ()).throw(OSError("denied")),
    )

    with pytest.raises(OSError, match="denied"):
        SkillMdDeleter(registry, skills_dir=tmp_skills_dir).delete("web-search")

    assert registry.exists("web-search")
    assert (tmp_skills_dir / "web-search").exists()


def test_delete_builtin_blocked(registry: SkillRegistry) -> None:
    """试图删 builtin 技能 (例如 'coder') 必须抛 BuiltinSkillError。"""
    deleter = SkillMdDeleter(registry)

    with pytest.raises(BuiltinSkillError) as exc_info:
        deleter.delete("coder")  # builtin name from backend/skills/builtin/coder.py

    assert "builtin" in str(exc_info.value).lower()
    assert "coder" in str(exc_info.value)


# ===== Task 2: 安全 + 边界 =====


def test_delete_missing_skill_404(tmp_skills_dir: Path, registry: SkillRegistry) -> None:
    deleter = SkillMdDeleter(registry, skills_dir=tmp_skills_dir)
    with pytest.raises(SkillMdNotFoundError):
        deleter.delete("does-not-exist")


def test_delete_invalid_name_400(tmp_skills_dir: Path, registry: SkillRegistry) -> None:
    deleter = SkillMdDeleter(registry, skills_dir=tmp_skills_dir)
    with pytest.raises(ValueError, match=r"Invalid skill name"):
        deleter.delete("../etc-passwd")
    with pytest.raises(ValueError, match=r"Invalid skill name"):
        deleter.delete("UPPER_CASE")  # 不允许大写


def test_delete_path_outside_skills_dir_blocked(tmp_path: Path, registry: SkillRegistry) -> None:
    """通过 Symbol 链或 type-bypass 试图让 path 跑出 skills_dir → 必须 ValueError。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "good").mkdir()

    deleter = SkillMdDeleter(registry, skills_dir=skills_dir)
    # 触发 _resolve_skills_dir 写入 self._skills_dir 缓存 (delete() 走此路径)
    deleter._resolve_skills_dir()
    outside = (tmp_path / "etc").resolve()  # 在 skills_dir 之外
    with pytest.raises(ValueError, match=r"outside skills_dir"):
        deleter._validate_path_under_skills_dir(outside)


def test_delete_unregisters_from_registry(tmp_skills_dir: Path, registry: SkillRegistry) -> None:
    """delete 后 registry 不再含该项 (registry unregister 已发生)。"""
    from backend.skills.skill_md.loader import register_skill_md_skills

    # 先 register 一个 SKILL.md skill
    register_skill_md_skills(registry, dirs=[tmp_skills_dir])
    assert registry.exists("web-search") is True

    deleter = SkillMdDeleter(registry, skills_dir=tmp_skills_dir)
    deleter.delete("web-search")

    assert registry.exists("web-search") is False


# ===== Task 3: FastAPI endpoint =====
#
# endpoint 走路由层模块级单例 ``_get_skill_adapter()``,在 lazy init 时
# 通过 ``discover_skill_md_dirs()`` 自动从 ``$SAGE_SKILLS_DIR`` 加载 SKILL.md。
# ``tmp_skills_dir`` fixture 已经设了 env, ``reset_skill_adapter`` 强制重建
# 单例 → 新单例从 tmp_path 加载 web-search。无需在测试里手工调
# ``register_skill_md_skills``(那会让 web-search 注册到测试本地 registry,
# 但 endpoint 走的是单例的另一个 registry)。


@pytest.mark.asyncio()
async def test_delete_endpoint_returns_200(
    tmp_skills_dir: Path, client, reset_skill_adapter
) -> None:
    """POST /api/v1/skills/{name}/delete 成功 → 200 + 安全的删除结果。"""
    # 触发 lazy init: 单例创建时 InprocSkillAdapter.__init__ 会调
    # register_skill_md_skills → discover_skill_md_dirs() → SAGE_SKILLS_DIR=tmp_path
    # → 自动加载 tmp_skills_dir/web-search/SKILL.md
    import backend.api.legacy_routes as routes_module

    adapter = routes_module._get_skill_adapter()
    # sanity: web-search 已注册到单例的 registry
    assert adapter.has_skill("web-search") is True

    response = await client.post("/api/v1/skills/web-search/delete")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["name"] == "web-search"
    assert body["base_dir"] == "."
    assert str(tmp_skills_dir) not in body["base_dir"]
    # 物理 unlink: 目录不存在
    assert (tmp_skills_dir / "web-search").exists() is False
    # registry unregister
    assert adapter.has_skill("web-search") is False


@pytest.mark.asyncio()
async def test_delete_endpoint_builtin_returns_400(
    tmp_skills_dir: Path, client, reset_skill_adapter
) -> None:
    """试图删 builtin → 400 + detail 含 'builtin'。"""
    response = await client.post("/api/v1/skills/coder/delete")

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["type"] == "builtin_skill"
    assert "内置技能" in detail["message"]


@pytest.mark.asyncio()
async def test_delete_endpoint_missing_returns_404(
    tmp_skills_dir: Path, client, reset_skill_adapter
) -> None:
    """试图删不存在的 skill → 404。"""
    response = await client.post("/api/v1/skills/never-existed/delete")

    assert response.status_code == 404, response.text
