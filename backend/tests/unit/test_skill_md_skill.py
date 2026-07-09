# mypy: disable-error-code="no-untyped-def,attr-defined,func-returns-value"
"""SkillMdSkill 包装类单测。

覆盖 backend.skills.skill_md.skill:
- SkillMdDocument dataclass
- SkillMdSkill(BaseSkill): _build_schema, execute
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from backend.skills.base import SkillSchema
from backend.skills.skill_md.skill import SkillMdDocument, SkillMdSkill

pytestmark = pytest.mark.unit


# =====================================================================
# helpers
# =====================================================================


def _make_doc(
    name: str = "test-skill",
    description: str = "A test skill",
    triggers: Optional[List[str]] = None,
    body: str = "Body content",
    version: Optional[str] = "1.0.0",
    metadata: Optional[dict] = None,
    raw_frontmatter: Optional[dict] = None,
    base_dir: Optional[Path] = None,
) -> SkillMdDocument:
    return SkillMdDocument(
        name=name,
        description=description,
        triggers=triggers or [],
        body=body,
        base_dir=base_dir or Path("/tmp/skills/test-skill"),
        version=version,
        metadata=metadata or {},
        raw_frontmatter=raw_frontmatter
        or {
            "name": name,
            "description": description,
        },
    )


# =====================================================================
# SkillMdDocument dataclass
# =====================================================================


def test_document_required_fields_only():
    """只填 name + description 也能构造, 其他字段默认值正常。"""
    doc = SkillMdDocument(name="x", description="y")
    assert doc.name == "x"
    assert doc.description == "y"
    assert doc.triggers == []
    assert doc.body == ""
    assert doc.base_dir is None
    assert doc.version is None
    assert doc.metadata == {}
    assert doc.raw_frontmatter == {}


def test_document_all_fields():
    doc = SkillMdDocument(
        name="x",
        description="y",
        triggers=["t1", "t2"],
        body="body",
        base_dir=Path("/tmp/x"),
        version="2.0.0",
        metadata={"k": "v"},
        raw_frontmatter={"name": "x", "description": "y"},
    )
    assert doc.triggers == ["t1", "t2"]
    assert doc.body == "body"
    assert doc.base_dir == Path("/tmp/x")
    assert doc.version == "2.0.0"
    assert doc.metadata == {"k": "v"}


# =====================================================================
# SkillMdSkill._build_schema
# =====================================================================


def test_schema_fields_from_frontmatter():
    doc = _make_doc(
        name="code-review",
        description="Review a diff",
        triggers=["review", "code review"],
    )
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/code-review"))
    schema = skill.schema
    assert isinstance(schema, SkillSchema)
    assert schema.name == "code-review"
    assert schema.description == "Review a diff"
    assert schema.triggers == ["review", "code review"]
    assert schema.parameters == {"type": "object", "properties": {}}
    assert schema.examples == []


def test_default_triggers_when_omitted():
    """frontmatter 未声明 triggers → 默认用 [name.lower()] 作为唯一触发词。"""
    doc = _make_doc(name="code-review", triggers=[])
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/code-review"))
    assert skill.schema.triggers == ["code-review"]


def test_schema_is_cached_across_calls():
    """重复访问 schema 返回同一对象(BaseSkill 已有的惰性 cache 行为)。"""
    doc = _make_doc()
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/test-skill"))
    s1 = skill.schema
    s2 = skill.schema
    assert s1 is s2


# =====================================================================
# SkillMdSkill.execute
# =====================================================================


def test_execute_returns_body_string_in_content():
    """execute() 把 body 原样放进 content。"""
    doc = _make_doc(name="x", body="## Heading\n\nbody text\n")
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/x"))
    result = skill.execute(params={}, context={})
    assert result.success is True
    assert result.content == "## Heading\n\nbody text\n"
    assert result.error is None


def test_execute_metadata_source_is_skillmd():
    """metadata['source'] 固定为 'skillmd'。"""
    doc = _make_doc()
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/test-skill"))
    result = skill.execute(params={}, context={})
    assert result.metadata["source"] == "skillmd"
    assert result.metadata["name"] == "test-skill"


def test_execute_metadata_version_passthrough():
    """version 字段透传到 metadata。"""
    doc = _make_doc(version="0.3.0")
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/test-skill"))
    result = skill.execute(params={}, context={})
    assert result.metadata["version"] == "0.3.0"


def test_execute_metadata_includes_raw_frontmatter():
    """原始 frontmatter 字典透传, 供聊天层做高级处理。"""
    raw = {
        "name": "x",
        "description": "y",
        "metadata": {"hermes": {"tags": ["python"]}},
    }
    doc = _make_doc(raw_frontmatter=raw)
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/x"))
    result = skill.execute(params={}, context={})
    assert result.metadata["frontmatter"] == raw


def test_execute_ignores_params_and_context():
    """v1 SKILL.md 不消费 params/context, execute 是幂等无副作用的。"""
    doc = _make_doc(body="static body")
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/test-skill"))
    r1 = skill.execute(params={"any": "thing"}, context={"tools": "fake"})
    r2 = skill.execute(params={}, context={})
    assert r1.content == r2.content == "static body"
    assert r1.success is True


def test_skill_repr_contains_name():
    doc = _make_doc(name="my-skill")
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/my-skill"))
    repr_str = repr(skill)
    assert "my-skill" in repr_str


# =====================================================================
# match() (继承自 BaseSkill) — 验证默认触发词匹配行为
# =====================================================================


def test_match_with_explicit_triggers():
    doc = _make_doc(name="x", triggers=["hello", "greet"])
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/x"))
    assert skill.match("please hello world") is True
    assert skill.match("unrelated text") is False


def test_match_with_default_triggers():
    """未声明 triggers → 默认用 name, 大小写不敏感。"""
    doc = _make_doc(name="code-review", triggers=[])
    skill = SkillMdSkill(doc, base_dir=Path("/tmp/skills/code-review"))
    assert skill.match("please do a CODE-REVIEW") is True
    assert skill.match("nothing here") is False
