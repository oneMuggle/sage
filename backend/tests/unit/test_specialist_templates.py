# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""M4-T2 — 内置模板库（spec §9 模板库）。

覆盖:

1. ``list_templates()`` — 返回 6 个模板，顺序 Sage 向导→写作→研究→编码→演示→Office；
   字段齐全（id/name/tagline/avatar/description/skill_count），不含 system_prompt
2. ``get_template_dir()`` — 非法 id / 不存在模板返回 None；合法 id 返回目录
3. ``instantiate_template()`` — 一键物化：id 前缀 ``specialist-<tpl>-<6hex>``；
   source 强制 ``builtin``；skills/memory_access/persona_ui/model_config 等
   字段正确落库；dropped_bindings=0；template_id 回填
4. ``sage-guide`` 例外：固定 id 幂等单例，返回 ``existed`` 标记
5. 模板物化失败（id 非法 / 模板不存在）抛 ValueError
6. 同一模板物化两次，id 不重复（``<6hex>`` 防冲突）
7. 模板物化后的专家通过 AgentRepository 可列出/检索，且 ``source`` 为 ``builtin``
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# =====================================================================
# helpers
# =====================================================================


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "templates-test.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


@pytest.fixture()
def template_env(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    root = tmp_path / "specialists"
    root.mkdir()
    monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(root))
    return root


# =====================================================================
# list_templates
# =====================================================================


class TestListTemplates:
    def test_returns_six_templates_in_canonical_order(self):
        from backend.services.specialist_templates import list_templates

        templates = list_templates()
        assert len(templates) == 6
        assert [t["id"] for t in templates] == [
            "sage-guide",
            "writing",
            "research",
            "coding",
            "presentation",
            "office",
        ]

    def test_each_template_has_required_fields(self):
        from backend.services.specialist_templates import list_templates

        for t in list_templates():
            assert t["id"]
            assert t["name"]
            assert t["avatar"]  # 未声明也用默认值
            assert t["tagline"]
            assert "description" in t
            assert "skill_count" in t
            assert isinstance(t["skill_count"], int)

    def test_does_not_expose_system_prompt(self):
        from backend.services.specialist_templates import list_templates

        for t in list_templates():
            assert "system_prompt" not in t
            assert "body" not in t

    def test_writing_template_metadata(self):
        from backend.services.specialist_templates import list_templates

        writing = next(t for t in list_templates() if t["id"] == "writing")
        assert writing["name"] == "写作专家"
        assert writing["avatar"] == "📝"
        assert writing["skill_count"] == 3


# =====================================================================
# get_template_dir
# =====================================================================


class TestGetTemplateDir:
    def test_unknown_returns_none(self):
        from backend.services.specialist_templates import get_template_dir

        assert get_template_dir("nonexistent") is None

    def test_invalid_id_returns_none(self):
        from backend.services.specialist_templates import get_template_dir

        assert get_template_dir("../etc") is None
        assert get_template_dir("") is None
        assert get_template_dir("WRITING") is None
        assert get_template_dir("a" * 64) is None

    def test_known_id_returns_dir_with_persona(self):
        from backend.services.specialist_templates import get_template_dir

        dir_ = get_template_dir("writing")
        assert isinstance(dir_, Path)
        assert dir_.name == "writing"
        assert (dir_ / "persona.md").is_file()


# =====================================================================
# instantiate_template
# =====================================================================


class TestInstantiateTemplate:
    def test_writing_instantiate_creates_agent(self, template_env):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_templates import instantiate_template

        result = instantiate_template("writing")
        assert result["id"].startswith("specialist-writing-")
        assert len(result["id"]) == len("specialist-writing-") + 6
        assert result["name"] == "写作专家"
        assert result["template_id"] == "writing"
        assert result["dropped_bindings"] == 0

        # agent 行落库
        agent = AgentRepository().get(result["id"])
        assert agent is not None
        assert agent["source"] == "builtin"
        assert agent["role"] == "specialist"
        assert agent["skills"] == ["writing", "polish-prose", "structure-outline"]
        assert agent["memory_access"] == ["user", "specialist"]
        assert agent["permission_mode"] == "workspace_write"
        assert agent["max_iterations"] == 10
        assert agent["persona_ui"]["avatar"] == "📝"
        assert agent["persona_ui"]["tagline"] == "专业写作助手"
        assert agent["model_config"]["temperature"] == 0.7

    def test_source_overridden_to_builtin(self, template_env):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_templates import instantiate_template

        # 即使模板 persona.md 里 source=builtin，这里也显式断言 override 生效
        result = instantiate_template("research")
        agent = AgentRepository().get(result["id"])
        assert agent["source"] == "builtin"

    def test_data_dir_created(self, template_env):
        from backend.services.specialist_templates import instantiate_template

        result = instantiate_template("coding")
        agent_dir = template_env / result["id"]
        assert agent_dir.is_dir()
        # coding persona 无 avatar.png/skills/knowledge → 子目录不应存在或为空
        # 关键是主目录被正确创建

    def test_id_unique_across_calls(self, template_env):
        from backend.services.specialist_templates import instantiate_template

        ids = set()
        # 5 个模板各物化一次，id 应全部不同
        for tpl in ("writing", "research", "coding", "presentation", "office"):
            result = instantiate_template(tpl)
            ids.add(result["id"])
        assert len(ids) == 5

    def test_unknown_template_raises(self, template_env):
        from backend.services.specialist_templates import instantiate_template

        with pytest.raises(ValueError, match="模板不存在"):
            instantiate_template("nonexistent")

    def test_invalid_id_raises(self, template_env):
        from backend.services.specialist_templates import instantiate_template

        with pytest.raises(ValueError, match="模板不存在"):
            instantiate_template("../etc")

    def test_all_templates_instantiate(self, template_env):
        """6 套模板全部物化成功，字段齐全。"""
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_templates import (
            instantiate_template,
            list_templates,
        )

        for t in list_templates():
            result = instantiate_template(t["id"])
            agent = AgentRepository().get(result["id"])
            assert agent is not None, f"模板 {t['id']} 物化后 agents 行缺失"
            assert agent["name"], f"模板 {t['id']} 缺少 name"
            assert agent["system_prompt"], f"模板 {t['id']} 缺少 system_prompt"
            if t["id"] != "sage-guide":
                assert (
                    "# 身份" in agent["system_prompt"]
                    or "身份" in agent["system_prompt"]
                )


# =====================================================================
# sage-guide 单例
# =====================================================================


class TestSageGuideSingleton:
    def test_instantiate_is_idempotent_fixed_id(self, template_env):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_templates import instantiate_template

        first = instantiate_template("sage-guide")
        second = instantiate_template("sage-guide")

        assert first["id"] == "sage-guide"
        assert second["id"] == "sage-guide"
        assert first["existed"] is False
        assert second["existed"] is True
        assert second["template_id"] == "sage-guide"
        assert AgentRepository().get("sage-guide") is not None

    def test_keeps_sage_docs_binding(self, template_env):
        from backend.data.agent_repo import AgentRepository
        from backend.services.specialist_templates import instantiate_template

        instantiate_template("sage-guide")
        agent = AgentRepository().get("sage-guide")

        bindings = agent["knowledge_bindings"]
        assert bindings
        assert bindings[0]["source_type"] == "sage_docs"
        assert agent["source"] == "builtin"

    def test_persona_body_matches_profile_prompt(self):
        from backend.agents.profiles import _SAGE_GUIDE_SYSTEM_PROMPT
        from backend.services.specialist_templates import get_template_dir

        template_dir = get_template_dir("sage-guide")
        text = (template_dir / "persona.md").read_text(encoding="utf-8")
        body = text.split("---", 2)[2].strip()

        assert body == _SAGE_GUIDE_SYSTEM_PROMPT
