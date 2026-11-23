"""Unit/integration tests for rulepack → Word style profile conversion."""

from __future__ import annotations

import pytest

from backend.api.office_word_style_routes import (
    WordStyleFromRulepackRequest,
    from_rulepack_endpoint,
)
from backend.office.word_rulepack_builtin import builtin_rulepacks
from backend.office.word_rulepack_models import WordRulePack, WordRuleSpec
from backend.office.word_style_profile import format_spec_from_rulepack


def _builtin(pack_id: str) -> WordRulePack:
    return next(pack for pack in builtin_rulepacks() if pack.id == pack_id)


def _rule(rule_id: str, kind: str, params: dict) -> WordRuleSpec:
    return WordRuleSpec(id=rule_id, title=rule_id, kind=kind, params=params)


def test_gb9704_rulepack_converts_to_profile() -> None:
    result = format_spec_from_rulepack(_builtin("gb-t-9704-general"))
    spec = result.format_spec
    assert spec.page is not None
    assert spec.page.size == "A4"
    assert spec.page.orientation == "portrait"
    assert spec.page.margins_cm.top == pytest.approx(3.7)
    assert spec.page.margins_cm.bottom == pytest.approx(3.5)
    assert spec.page.margins_cm.left == pytest.approx(2.8)
    assert spec.page.margins_cm.right == pytest.approx(2.6)
    assert spec.body is not None
    assert spec.body.font_family == "仿宋_GB2312"
    assert spec.body.font_size_pt == pytest.approx(16)
    assert spec.footer is not None
    assert spec.footer.page_number is True
    assert result.applied_rule_ids
    assert result.unmapped == []


def test_custom_rulepack_maps_heading_caption_and_paragraph() -> None:
    pack = WordRulePack(
        id="custom",
        name="custom",
        rules=[
            _rule(
                "r1",
                "style.font",
                {"style": "Heading 1", "font_east_asia": "黑体", "size_pt": 16},
            ),
            _rule(
                "r2",
                "style.font",
                {"style": "图题", "font_east_asia": "楷体", "size_pt": 10.5},
            ),
            _rule(
                "r3",
                "style.paragraph",
                {
                    "style": "Normal",
                    "line_spacing_pt": 28,
                    "first_line_indent_cm": 1.1,
                    "alignment": "justify",
                },
            ),
            _rule("r4", "style.font", {"style": "页眉文字", "font_east_asia": "宋体"}),
            _rule("r5", "content.caption_sequence", {}),
        ],
    )
    result = format_spec_from_rulepack(pack)
    spec = result.format_spec
    assert spec.headings is not None
    assert spec.headings["h1"].font_family == "黑体"
    assert spec.headings["h1"].font_size_pt == pytest.approx(16)
    assert spec.caption is not None
    assert spec.caption.font_family == "楷体"
    assert spec.caption.font_size_pt == pytest.approx(10.5)
    assert spec.body is not None
    assert spec.body.line_spacing_pt == pytest.approx(28)
    assert spec.body.first_line_indent_cm == pytest.approx(1.1)
    assert spec.body.align == "justify"
    assert {u.rule_id for u in result.unmapped} == {"r4", "r5"}
    assert {"r1", "r2", "r3"} <= set(result.applied_rule_ids)


def test_conflicting_style_values_first_wins_with_warning() -> None:
    pack = WordRulePack(
        id="conflict",
        name="conflict",
        rules=[
            _rule("a", "style.font", {"style": "Normal", "size_pt": 12}),
            _rule("b", "style.font", {"style": "Normal", "size_pt": 14}),
        ],
    )
    result = format_spec_from_rulepack(pack)
    assert result.format_spec.body.font_size_pt == pytest.approx(12)
    assert any("冲突" in warning for warning in result.warnings)
    assert "b" not in result.applied_rule_ids


def test_invalid_values_are_unmapped_not_fatal() -> None:
    pack = WordRulePack(
        id="invalid",
        name="invalid",
        rules=[
            _rule("bad-size", "style.font", {"style": "Normal", "size_pt": 999}),
            _rule(
                "bad-align",
                "style.paragraph",
                {"style": "Normal", "alignment": "diagonal"},
            ),
        ],
    )
    result = format_spec_from_rulepack(pack)
    assert (
        result.format_spec.body is None
        or result.format_spec.body.font_size_pt is None
    )
    assert {u.rule_id for u in result.unmapped} == {"bad-size", "bad-align"}


def test_from_rulepack_endpoint_builtin_pack() -> None:
    result = from_rulepack_endpoint(
        WordStyleFromRulepackRequest(rulepack_id="gb-t-9704-general")
    )
    assert result.ok is True
    assert result.format_spec.body.font_family == "仿宋_GB2312"


def test_from_rulepack_endpoint_inline_pack() -> None:
    pack = WordRulePack(
        id="inline",
        name="inline",
        rules=[_rule("t", "style.font", {"style": "Title", "size_pt": 22})],
    )
    result = from_rulepack_endpoint(WordStyleFromRulepackRequest(rulepack=pack))
    assert result.format_spec.title is not None
    assert result.format_spec.title.font_size_pt == pytest.approx(22)
