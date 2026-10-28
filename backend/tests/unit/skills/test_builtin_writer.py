"""R151 — 内置写作技能（WriterSkill）单元测试。

覆盖：schema 契约（required=[type, topic]）、无 LLM 模拟回退
（metadata.mock、四类型模板）、prompt 构建（四类型特征文案）、LLM
分派与异常映射。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.skills.builtin.writer import WriterSkill

pytestmark = pytest.mark.unit


def _llm(capture):
    def complete(prompt):
        capture.append(prompt)
        return f"llm: {prompt[:10]}"

    return SimpleNamespace(complete=complete)


def test_schema_contract():
    schema = WriterSkill().schema
    assert schema.name == "writer"
    assert schema.parameters["required"] == ["type", "topic"]
    assert set(schema.parameters["properties"]["type"]["enum"]) == {
        "article", "email", "report", "social", "other",
    }


def test_no_llm_returns_mock_content():
    out = WriterSkill().execute({"type": "article", "topic": "AI"}, {})
    assert out.success is True
    assert "关于「AI」的文章" in out.content
    assert out.metadata["mock"] is True
    assert out.metadata["type"] == "article"
    assert out.metadata["topic"] == "AI"


@pytest.mark.parametrize(
    ("article_type", "fragment"),
    [
        ("article", "文章"),
        ("email", "商务沟通"),
        ("report", "分析报告"),
        ("social", "分享关于"),
    ],
)
def test_mock_templates_per_type(article_type, fragment):
    out = WriterSkill().execute({"type": article_type, "topic": "T"}, {})
    assert out.success is True
    assert fragment in out.content


def test_unknown_type_falls_back_to_article_template():
    out = WriterSkill().execute({"type": "poem", "topic": "T"}, {})
    assert "文章" in out.content  # 未知类型回退 article 模板


def test_with_llm_builds_prompt_and_returns_completion():
    prompts = []
    llm = SimpleNamespace(complete=lambda p: (prompts.append(p), f"done: {p[:6]}")[1])
    out = WriterSkill().execute(
        {"type": "article", "topic": "AI", "length": "long", "style": "casual"},
        {"llm": llm},
    )
    assert out.success is True
    assert out.content.startswith("done:")
    assert len(prompts) == 1
    assert "「AI」" in prompts[0]
    assert "1500-2000 字" in prompts[0]  # long 档
    assert "casual" in prompts[0]
    assert "mock" not in out.metadata


def test_prompt_length_map_medium_default():
    prompts = []
    llm = SimpleNamespace(complete=lambda p: (prompts.append(p), "x")[1])
    WriterSkill().execute({"type": "article", "topic": "T"}, {"llm": llm})
    assert "500-800 字" in prompts[0]


def test_llm_exception_maps_to_error():
    def complete(_p):
        raise RuntimeError("quota")

    out = WriterSkill().execute(
        {"type": "article", "topic": "T"}, {"llm": SimpleNamespace(complete=complete)}
    )
    assert out.success is False
    assert "写作失败" in out.error
    assert "quota" in out.error
