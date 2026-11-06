"""M3: 技能存储可见性路由测试。

覆盖:
- GET /skills/storage: 可写根解析优先级（env > preference > default）、roots、风险标记
- GET /skills/{name}/location: builtin/不存在 → 404；允许根内 → 200；越界 → 403
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

import pytest
from fastapi import HTTPException

from backend.api import skill_storage_export_routes as routes

pytestmark = pytest.mark.unit


class _FakeAdapter:
    def __init__(
        self,
        locations: Dict[str, Optional[str]],
        listed: Optional[List[dict]] = None,
    ):
        self._locations = locations
        self._listed = listed or []

    def skill_location(self, name: str) -> Optional[str]:
        return self._locations.get(name)

    def list_skills_extended(self, allowed=None):
        return list(self._listed)


class TestSkillsStorage:
    def test_env_override_wins(self, tmp_path: Path, monkeypatch):
        env_dir = tmp_path / "env-skills"
        env_dir.mkdir()
        monkeypatch.setenv("SAGE_SKILLS_DIR", str(env_dir))

        payload = routes.get_skills_storage()

        assert payload["writable_root"] == str(env_dir)
        assert payload["writable_source"] == "env"
        assert "roots" in payload
        assert "installed_app_dir" in payload
        assert "writable_in_app_dir" in payload

    def test_default_root_is_home_sage_skills(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("SAGE_SKILLS_DIR", raising=False)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        # 隔离 preference：让 read_skills_dir_preference 返回 None
        monkeypatch.setattr(
            "backend.skills.skill_md.skills_dir_policy.read_skills_dir_preference",
            lambda repo=None: None,
        )

        payload = routes.get_skills_storage()

        assert payload["writable_source"] == "default"
        assert payload["writable_root"] == str(fake_home / ".sage" / "skills")


class TestSkillLocation:
    def test_builtin_or_missing_returns_404(self, monkeypatch):
        monkeypatch.setattr(
            routes, "_get_skill_adapter", lambda: _FakeAdapter({"builtin-x": None})
        )
        with pytest.raises(HTTPException) as exc:
            routes.get_skill_location("builtin-x")
        assert exc.value.status_code == 404

    def test_path_outside_allowed_roots_returns_403(self, tmp_path: Path, monkeypatch):
        outside = tmp_path / "outside" / "skill"
        outside.mkdir(parents=True)
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setattr(
            routes, "_get_skill_adapter", lambda: _FakeAdapter({"evil": str(outside)})
        )
        monkeypatch.setattr(
            "backend.skills.skill_md.loader.discover_skill_md_dirs", lambda: [allowed]
        )
        monkeypatch.setattr(
            "backend.skills.skill_md.loader._discover_shipped_dir", lambda: None
        )

        with pytest.raises(HTTPException) as exc:
            routes.get_skill_location("evil")
        assert exc.value.status_code == 403

    def test_skill_inside_allowed_root_returns_real_path(self, tmp_path: Path, monkeypatch):
        allowed = tmp_path / "allowed"
        skill_dir = allowed / "my-skill"
        skill_dir.mkdir(parents=True)
        monkeypatch.setattr(
            routes, "_get_skill_adapter", lambda: _FakeAdapter({"my-skill": str(skill_dir)})
        )
        monkeypatch.setattr(
            "backend.skills.skill_md.loader.discover_skill_md_dirs", lambda: [allowed]
        )
        monkeypatch.setattr(
            "backend.skills.skill_md.loader._discover_shipped_dir", lambda: None
        )

        payload = routes.get_skill_location("my-skill")

        assert payload["name"] == "my-skill"
        assert Path(payload["path"]) == skill_dir.resolve()

    def test_symlink_inside_root_is_allowed(self, tmp_path: Path, monkeypatch):
        """用户根内的软链接技能（链接本身在根内）应被允许，即使 resolve 指向根外。"""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = allowed / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported on this platform")
        monkeypatch.setattr(
            routes, "_get_skill_adapter", lambda: _FakeAdapter({"linked": str(link)})
        )
        monkeypatch.setattr(
            "backend.skills.skill_md.loader.discover_skill_md_dirs", lambda: [allowed]
        )
        monkeypatch.setattr(
            "backend.skills.skill_md.loader._discover_shipped_dir", lambda: None
        )

        payload = routes.get_skill_location("linked")

        assert payload["name"] == "linked"
        assert Path(payload["path"]) == outside.resolve()


class TestSkillExport:
    def _make_skill(self, allowed: Path, name: str = "my-skill") -> Path:
        skill_dir = allowed / name
        (skill_dir / "scripts").mkdir(parents=True)
        (skill_dir / "assets").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        (skill_dir / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")
        (skill_dir / "assets" / "logo.png").write_bytes(b"png")
        # 非白名单目录 / 顶层杂文件 → 不应进入 zip
        (skill_dir / "secret.txt").write_text("no", encoding="utf-8")
        (skill_dir / "misc").mkdir()
        (skill_dir / "misc" / "x.txt").write_text("no", encoding="utf-8")
        return skill_dir

    def _patch_roots(self, monkeypatch, allowed: Path) -> None:
        monkeypatch.setattr(
            "backend.skills.skill_md.loader.discover_skill_md_dirs", lambda: [allowed]
        )
        monkeypatch.setattr(
            "backend.skills.skill_md.loader._discover_shipped_dir", lambda: None
        )

    def test_single_export_contains_only_allowed_files(self, tmp_path: Path, monkeypatch):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        skill_dir = self._make_skill(allowed)
        self._patch_roots(monkeypatch, allowed)
        monkeypatch.setattr(
            routes,
            "_get_skill_adapter",
            lambda: _FakeAdapter({"my-skill": str(skill_dir)}),
        )

        response = routes.export_skill("my-skill")
        assert response.media_type == "application/zip"
        with zipfile.ZipFile(BytesIO(response.body)) as zf:
            names = set(zf.namelist())
        assert "my-skill/SKILL.md" in names
        assert "my-skill/scripts/run.py" in names
        assert "my-skill/assets/logo.png" in names
        assert not any("secret" in n for n in names)
        assert not any("misc" in n for n in names)

    def test_builtin_is_not_exportable(self, monkeypatch):
        monkeypatch.setattr(
            routes, "_get_skill_adapter", lambda: _FakeAdapter({"builtin-x": None})
        )
        with pytest.raises(HTTPException) as exc:
            routes.export_skill("builtin-x")
        assert exc.value.status_code == 404

    def test_batch_export_only_includes_mine(self, tmp_path: Path, monkeypatch):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        mine = self._make_skill(allowed, "mine-skill")
        shipped = self._make_skill(allowed, "shipped-skill")
        shipped_resolved = shipped.resolve()
        self._patch_roots(monkeypatch, allowed)
        monkeypatch.setattr(
            routes,
            "_get_skill_adapter",
            lambda: _FakeAdapter(
                {
                    "mine-skill": str(mine),
                    "shipped-skill": str(shipped),
                    "builtin-x": None,
                },
                listed=[
                    {"name": "mine-skill", "origin": "user"},
                    {"name": "shipped-skill", "origin": "shipped"},
                    {"name": "builtin-x", "origin": "builtin"},
                ],
            ),
        )
        # shipped 并不在 shipped_root 之下，但 origin 过滤会先排除它
        assert shipped_resolved.is_dir()

        response = routes.export_my_skills(scope="mine")
        with zipfile.ZipFile(BytesIO(response.body)) as zf:
            names = zf.namelist()
        assert any(n.startswith("mine-skill/") for n in names)
        assert not any(n.startswith("shipped-skill/") for n in names)
        assert not any(n.startswith("builtin-x/") for n in names)
