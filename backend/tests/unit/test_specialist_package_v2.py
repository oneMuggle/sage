# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""M4-T1 — 专家包 v2 格式与导入侧安全钳制（spec §8.3 / §11）。

覆盖:

1. v2 完整字段往返：导出 → 再导入后，全部 profile 字段与源 agent 一致
   （除 ``id`` 必生成新 id，``source`` 强制 ``imported``，
   非 ``specialist_private`` 的知识绑定被丢弃并计入 ``dropped_bindings``）
2. v1 向后兼容：只含 ``name/version/source`` 的 v1 包仍可导入
3. 安全钳制：
   - ``role`` 强制 ``specialist``
   - ``permission_mode=full_access`` 降级为 ``workspace_write``
   - 非法 permission_mode 重置为 ``workspace_write``
   - 字符串数组去重限量；memory_access 白名单过滤
   - knowledge_bindings 非 specialist_private 丢弃并计数
   - 嵌套映射非法类型（bytes/set）递归丢弃
   - max_iterations 越界钳制到 [1, 50]
   - version 越界钳制到 [1, 9999]
4. install_specialist_from_dir + requested_id：
   - 显式 id 合法时使用
   - 显式 id 非法时 ValueError
   - 显式 id 已存在时 ValueError + 目录回滚
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# =====================================================================
# helpers
# =====================================================================


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "specialist-v2.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


@pytest.fixture()
def v2_env(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    root = tmp_path / "specialists"
    root.mkdir()
    monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(root))

    from backend.data.agent_repo import AgentRepository

    # 构造一个字段齐全的源专家（v2 全部字段）
    AgentRepository().upsert(
        {
            "id": "writer-v2",
            "name": "写作专家",
            "role": "specialist",
            "system_prompt": "# 身份\n\n你是一位专业写作助手。",
            "description": "专注润色与结构化写作",
            "source": "user",
            "version": 3,
            "enabled": True,
            "max_iterations": 20,
            "permission_mode": "workspace_write",
            "skills": ["writing", "polish-prose"],
            "tools": ["search_web"],
            "memory_access": ["user", "specialist"],
            "model_config": {"model": "", "temperature": 0.7, "max_tokens": 0},
            "memory_policy": {
                "write_scope": "specialist",
                "read_scopes": ["specialist", "project", "user"],
            },
            "persona_ui": {
                "avatar": "📝",
                "tagline": "专业写作助手",
                "greeting": "你好，我是写作专家。",
                "suggested_prompts": ["帮我润色", "改写这段"],
            },
            "knowledge_bindings": [
                {
                    "id": "kb-private",
                    "agent_id": "writer-v2",
                    "source_type": "specialist_private",
                    "source_id": "writer-v2",
                    "name": "private",
                    "filters": {"top_k": 5},
                    "created_at": 1_700_000_000,
                },
                {
                    "id": "kb-wiki",
                    "agent_id": "writer-v2",
                    "source_type": "wiki_project",
                    "source_id": "proj-1",
                    "name": "wiki",
                    "filters": {},
                    "created_at": 1_700_000_001,
                },
            ],
        }
    )
    # 数据目录：avatar + skills + knowledge
    agent_dir = root / "writer-v2"
    agent_dir.mkdir()
    (agent_dir / "avatar.png").write_bytes(b"PNG\x00" * 64)
    (agent_dir / "skills" / "polish-prose").mkdir(parents=True)
    (agent_dir / "skills" / "polish-prose" / "SKILL.md").write_text(
        "---\nname: polish-prose\n---\n# 润色\n", encoding="utf-8"
    )
    (agent_dir / "knowledge").mkdir()
    (agent_dir / "knowledge" / "style-guide.md").write_text(
        "# 文风\n", encoding="utf-8"
    )
    return root, "writer-v2"


def _make_zip(tmp_path: Path, files: dict) -> Path:
    path = tmp_path / "package.sage"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in files.items():
            zf.writestr(arcname, content.encode("utf-8") if isinstance(content, str) else content)
    return path


# =====================================================================
# 1. v2 完整字段往返
# =====================================================================


class TestPackageV2Roundtrip:
    def test_full_roundtrip_preserves_all_fields(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_exporter import (
            PACKAGE_FORMAT_VERSION,
            export_specialist,
        )
        from backend.services.specialist_importer import import_specialist

        root, agent_id = v2_env
        zip_path = export_specialist(agent_id)
        try:
            # 验证 v2 frontmatter
            with zipfile.ZipFile(zip_path) as zf:
                persona = zf.read("persona.md").decode("utf-8")
                assert f"format_version: {PACKAGE_FORMAT_VERSION}" in persona
                assert "写作专家" in persona
                assert "专业写作助手" in persona
                assert "workspace_write" in persona

            result = import_specialist(zip_path)
            new_id = result["id"]
            assert new_id != agent_id
            # 跨机器不可移植：wiki_project 被丢弃
            assert result["dropped_bindings"] == 1

            row = AgentRepository().get(new_id)
            assert row is not None
            # 核心字段保留
            assert row["name"] == "写作专家"
            assert row["role"] == "specialist"
            assert row["description"] == "专注润色与结构化写作"
            assert row["version"] == 3
            assert row["source"] == "imported"  # 外部导入强制
            assert row["enabled"] is True
            assert row["max_iterations"] == 20
            assert row["permission_mode"] == "workspace_write"
            assert row["skills"] == ["writing", "polish-prose"]
            assert row["tools"] == ["search_web"]
            assert row["memory_access"] == ["user", "specialist"]
            assert row["model_config"] == {"model": "", "temperature": 0.7, "max_tokens": 0}
            assert row["memory_policy"] == {
                "write_scope": "specialist",
                "read_scopes": ["specialist", "project", "user"],
            }
            assert row["persona_ui"]["avatar"] == "📝"
            assert row["persona_ui"]["tagline"] == "专业写作助手"
            assert row["persona_ui"]["greeting"] == "你好，我是写作专家。"
            assert row["persona_ui"]["suggested_prompts"] == ["帮我润色", "改写这段"]
            # 知识绑定仅保留 specialist_private，重绑新 id
            kb = row["knowledge_bindings"]
            assert len(kb) == 1
            assert kb[0]["source_type"] == "specialist_private"
            assert kb[0]["agent_id"] == new_id
            assert kb[0]["source_id"] == new_id

            # 文件：avatar / skills / knowledge
            new_dir = root / new_id
            assert (new_dir / "avatar.png").is_file()
            assert (new_dir / "skills" / "polish-prose" / "SKILL.md").is_file()
            assert (new_dir / "knowledge" / "style-guide.md").is_file()

            # system_prompt body 保持
            assert "专业写作助手" in row["system_prompt"]
        finally:
            shutil.rmtree(zip_path.parent, ignore_errors=True)


# =====================================================================
# 2. v1 向后兼容
# =====================================================================


class TestV1Backcompat:
    def test_v1_package_still_imports(self, v2_env, tmp_path):
        """v1 包（只有 name/version/source）仍能导入，字段用默认补齐。"""
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        v1_persona = (
            "---\n"
            "name: 旧版专家\n"
            "version: 1\n"
            "source: user\n"
            "---\n\n"
            "# 身份\n\n旧版 system prompt。\n"
        )
        zip_path = _make_zip(tmp_path, {"persona.md": v1_persona})
        result = import_specialist(zip_path)
        assert result["name"] == "旧版专家"
        row = AgentRepository().get(result["id"])
        assert row is not None
        assert row["role"] == "specialist"
        assert row["source"] == "imported"
        assert row["version"] == 1
        assert row["permission_mode"] == "workspace_write"
        assert row["skills"] == []
        assert row["tools"] == []
        assert row["memory_access"] == []
        assert row["model_config"] == {}
        assert row["persona_ui"] == {}
        assert row["knowledge_bindings"] == []
        assert "旧版 system prompt" in row["system_prompt"]


# =====================================================================
# 3. 安全钳制
# =====================================================================


class TestSafetyClamps:
    def _frontmatter(self, overrides: dict) -> str:
        import yaml

        base = {
            "format_version": 2,
            "name": "钳制专家",
            "version": 1,
            "source": "user",
        }
        base.update(overrides)
        return f"---\n{yaml.safe_dump(base, allow_unicode=True, sort_keys=False).strip()}\n---\n\n# 身份\n\n钳制。\n"

    def test_role_forced_specialist(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        zip_path = _make_zip(tmp_path, {"persona.md": self._frontmatter({})})
        result = import_specialist(zip_path)
        row = AgentRepository().get(result["id"])
        assert row["role"] == "specialist"

    def test_full_access_downgraded(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        zip_path = _make_zip(
            tmp_path,
            {"persona.md": self._frontmatter({"permission_mode": "full_access"})},
        )
        result = import_specialist(zip_path)
        row = AgentRepository().get(result["id"])
        assert row["permission_mode"] == "workspace_write"

    def test_invalid_permission_mode_reset(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        zip_path = _make_zip(
            tmp_path,
            {"persona.md": self._frontmatter({"permission_mode": "superuser"})},
        )
        result = import_specialist(zip_path)
        row = AgentRepository().get(result["id"])
        assert row["permission_mode"] == "workspace_write"

    def test_string_arrays_dedup_and_limit(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        dupes = ["writing", "writing", "polish", "polish"]
        zip_path = _make_zip(
            tmp_path,
            {"persona.md": self._frontmatter({"skills": dupes, "tools": dupes})},
        )
        result = import_specialist(zip_path)
        row = AgentRepository().get(result["id"])
        assert row["skills"] == ["writing", "polish"]
        assert row["tools"] == ["writing", "polish"]

    def test_memory_access_whitelist(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        zip_path = _make_zip(
            tmp_path,
            {"persona.md": self._frontmatter(
                {"memory_access": ["user", "evil", "project", "bogus"]}
            )},
        )
        result = import_specialist(zip_path)
        row = AgentRepository().get(result["id"])
        assert row["memory_access"] == ["user", "project"]

    def test_non_specialist_private_bindings_dropped(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        bindings = [
            {"id": "a", "agent_id": "x", "source_type": "specialist_private",
             "source_id": "x", "name": "private", "filters": {}},
            {"id": "b", "agent_id": "x", "source_type": "wiki_project",
             "source_id": "p", "name": "wiki", "filters": {}},
            {"id": "c", "agent_id": "x", "source_type": "project_material",
             "source_id": "m", "name": "material", "filters": {}},
            {"id": "d", "agent_id": "x", "source_type": "workspace_fts",
             "source_id": "w", "name": "fts", "filters": {}},
            "not-a-dict",  # 非法元素也计入 dropped
        ]
        zip_path = _make_zip(
            tmp_path,
            {"persona.md": self._frontmatter({"knowledge_bindings": bindings})},
        )
        result = import_specialist(zip_path)
        assert result["dropped_bindings"] == 4
        row = AgentRepository().get(result["id"])
        assert len(row["knowledge_bindings"]) == 1
        assert row["knowledge_bindings"][0]["source_type"] == "specialist_private"
        assert row["knowledge_bindings"][0]["agent_id"] == result["id"]

    def test_mapping_sanitizer_drops_unsafe_types(self, v2_env, tmp_path):
        """mapping 字段非 JSON 安全的值（bytes/set/自定义对象）丢弃。"""
        from backend.services.specialist_importer import _sanitize_mapping

        result = _sanitize_mapping(
            {
                "keep": "ok",
                "nested": {"a": 1, "b": {b"bytes": "x"}},
                "list": [1, "ok", b"drop-me"],
                "set": {1, 2},
            }
        )
        assert result == {"keep": "ok", "nested": {"a": 1, "b": {}}, "list": [1, "ok"]}
        # 顶层 set 整个被丢弃（非 dict → 返回 {}）
        assert _sanitize_mapping({1, 2}) == {}

    def test_max_iterations_clamped(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        zip_path = _make_zip(
            tmp_path,
            {"persona.md": self._frontmatter({"max_iterations": 999})},
        )
        result = import_specialist(zip_path)
        row = AgentRepository().get(result["id"])
        assert row["max_iterations"] == 50

    def test_version_clamped(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import import_specialist

        zip_path = _make_zip(
            tmp_path,
            {"persona.md": self._frontmatter({"version": -10})},
        )
        result = import_specialist(zip_path)
        row = AgentRepository().get(result["id"])
        assert row["version"] == 1  # minimum


# =====================================================================
# 4. install_specialist_from_dir + requested_id
# =====================================================================


class TestInstallFromDir:
    def _frontmatter(self, overrides: dict) -> str:
        import yaml

        base = {"name": "x", "version": 1, "source": "user"}
        base.update(overrides)
        return f"---\n{yaml.safe_dump(base, allow_unicode=True, sort_keys=False).strip()}\n---\n\n# body\n"

    def test_explicit_id_used(self, v2_env, tmp_path):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import install_specialist_from_dir

        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "persona.md").write_text(
            "---\nname: 模板专家\nversion: 1\nsource: builtin\n---\n\n# 身份\n\n模板。\n",
            encoding="utf-8",
        )
        result = install_specialist_from_dir(
            tpl_dir, requested_id="builtin-writing-001", source_override="builtin"
        )
        assert result["id"] == "builtin-writing-001"
        assert result["dropped_bindings"] == 0

        row = AgentRepository().get("builtin-writing-001")
        assert row is not None
        assert row["source"] == "builtin"

    def test_explicit_id_unsafe_raises(self, v2_env, tmp_path):
        from backend.services.specialist_importer import install_specialist_from_dir

        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "persona.md").write_text(
            "---\nname: x\n---\nbody\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="非法 agent_id"):
            install_specialist_from_dir(tpl_dir, requested_id="../etc/passwd")

    def test_explicit_id_already_exists_rolls_back(
        self, v2_env, tmp_path
    ):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_importer import install_specialist_from_dir
        from backend.skills.specialist_skills import specialists_root

        AgentRepository().upsert(
            {"id": "existing-agent", "name": "existing", "role": "specialist"}
        )
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "persona.md").write_text(
            "---\nname: y\n---\nbody\n", encoding="utf-8"
        )
        (tpl_dir / "knowledge").mkdir()
        (tpl_dir / "knowledge" / "x.md").write_text("x", encoding="utf-8")

        with pytest.raises(ValueError, match="已存在"):
            install_specialist_from_dir(tpl_dir, requested_id="existing-agent")
        assert not (specialists_root() / "existing-agent" / "knowledge" / "x.md").exists()
