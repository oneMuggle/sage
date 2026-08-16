"""M2b 审查加固 — ask_user_question 参数校验与载荷规范化回归。

覆盖:
- label 唯一性校验（重复 label → 两卡片联动选中的根因）
- 非字符串 description 拒绝（穿透到 React 会炸 UI 的根因）
- QuestionRequest.create 的二道防线规范化（非 str → None）
"""

from __future__ import annotations

import pytest

from backend.services.question_gate import QuestionRequest
from backend.tools.ask_user_tool import validate_ask_user_args

pytestmark = pytest.mark.unit


def _valid_args(**overrides):
    args = {
        "question": "选择输出格式?",
        "header": "输出格式",
        "options": [
            {"label": "Markdown", "description": "纯文本报告"},
            {"label": "PDF"},
        ],
        "multi_select": False,
    }
    args.update(overrides)
    return args


def test_validate_accepts_well_formed_args():
    """合法参数 → None（放行）。"""
    assert validate_ask_user_args(_valid_args()) is None


@pytest.mark.parametrize(
    "options",
    [
        [{"label": "A"}, {"label": "A"}],
        [{"label": "dup", "description": "x"}, {"label": "dup"}],
    ],
)
def test_validate_rejects_duplicate_labels(options):
    """重复 label → 拒绝（前端单选语义下会联动选中）。"""
    error = validate_ask_user_args(_valid_args(options=options))
    assert error is not None
    assert "重复" in error


@pytest.mark.parametrize("bad_description", [{"evil": True}, 42, ["nested"], ("t",)])
def test_validate_rejects_nonstring_description(bad_description):
    """非字符串 description → 拒绝（防穿透到 React 渲染层炸 UI）。"""
    options = [{"label": "A", "description": bad_description}, {"label": "B"}]
    error = validate_ask_user_args(_valid_args(options=options))
    assert error is not None
    assert "description" in error


def test_validate_rejects_nonstring_header():
    """header 必须是字符串（可选）。"""
    error = validate_ask_user_args(_valid_args(header=["chip"]))
    assert error is not None
    assert "header" in error


def test_create_normalizes_nonstring_description_to_none():
    """gate 二道防线: 畸形 description 落为 None，绝不穿透。"""
    req = QuestionRequest.create(
        question="q",
        options=[
            {"label": "a", "description": {"evil": True}},
            {"label": "b", "description": 42},
            {"label": "c", "description": "valid"},
        ],
    )
    assert req.options[0]["description"] is None
    assert req.options[1]["description"] is None
    assert req.options[2]["description"] == "valid"


def test_create_normalizes_nonstring_header_to_none():
    """gate 二道防线: 非字符串 header 落为 None。"""
    req = QuestionRequest.create(question="q", options=[], header={"x": 1})  # type: ignore[arg-type]
    assert req.header is None
