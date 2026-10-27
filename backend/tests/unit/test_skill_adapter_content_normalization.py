"""SkillResult.content 统一为 str (缺口 #9)。

技能实现可能返回 dict / list / None / int —— 前端需要字符串。
归一化 helper 在 adapter 执行路径统一转换, 前端 fallback 仍保留作为 defense-in-depth。
"""

from __future__ import annotations

import json

import pytest

from backend.adapters.out.skill.inproc import normalize_skill_content

pytestmark = pytest.mark.unit


def test_str_passthrough():
    assert normalize_skill_content("hello") == "hello"


def test_none_becomes_empty():
    assert normalize_skill_content(None) == ""


def test_dict_becomes_json():
    out = normalize_skill_content({"answer": 42, "msg": "你好"})
    parsed = json.loads(out)
    assert parsed == {"answer": 42, "msg": "你好"}
    # ensure_ascii=False: 中文保持可读
    assert "你好" in out


def test_list_becomes_json():
    out = normalize_skill_content([1, 2, 3])
    assert json.loads(out) == [1, 2, 3]


def test_int_becomes_str():
    assert normalize_skill_content(42) == "42"


def test_non_json_serializable_falls_back_to_str():
    # tuple is JSON-serializable as array; dict with custom object uses default=str
    class _Custom:
        def __str__(self):
            return "custom-value"

    out = normalize_skill_content({"obj": _Custom()})
    parsed = json.loads(out)
    assert parsed["obj"] == "custom-value"
