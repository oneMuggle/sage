"""事实侦察清单解析器单测（2026-11-27）。"""
from __future__ import annotations

import json

from backend.orchestration.scout_facts import (
    SCOUT_CLIENT_META_MAX_BYTES,
    SCOUT_FACTS_MAX_ITEMS,
    build_client_meta_json,
    parse_scout_facts,
    to_detail,
)


def test_empty_input_yields_no_facts():
    assert parse_scout_facts("") == []
    assert parse_scout_facts("   \n  \n") == []


def test_strips_common_bullet_prefixes():
    raw = (
        "- 第一条事实内容足够长可以判定\n"
        "* 第二条事实内容足够长可以判定\n"
        "• 第三条事实内容足够长可以判定\n"
        "1. 第四条事实内容足够长可以判定\n"
        "2) 第五条事实内容足够长可以判定\n"
        "① 第六条事实内容足够长可以判定\n"
    )
    facts = parse_scout_facts(raw)
    assert [f["text"] for f in facts] == [
        "第一条事实内容足够长可以判定",
        "第二条事实内容足够长可以判定",
        "第三条事实内容足够长可以判定",
        "第四条事实内容足够长可以判定",
        "第五条事实内容足够长可以判定",
        "第六条事实内容足够长可以判定",
    ]
    assert all(f["source"] == "" for f in facts)


def test_splits_parenthesised_source():
    facts = parse_scout_facts("- 某框架在 2024 年发布（来源：官方博客）")
    assert facts == [
        {"text": "某框架在 2024 年发布", "source": "官方博客"},
    ]


def test_splits_ascii_bracket_source():
    facts = parse_scout_facts("[来源: 论文 A] 某方法在基准上领先")
    assert facts == [{"text": "某方法在基准上领先", "source": "论文 A"}]


def test_splits_trailing_plain_source():
    facts = parse_scout_facts("- 某组件默认启用并发 来源：README 第三章")
    assert facts == [
        {"text": "某组件默认启用并发", "source": "README 第三章"},
    ]


def test_keeps_line_when_source_cannot_be_split_confidently():
    """正文太短说明拆错了（整行几乎只有来源）—— 保守地整行保留。"""
    facts = parse_scout_facts("根据来源：某文献")
    assert facts == [{"text": "根据来源：某文献", "source": ""}]


def test_keeps_line_when_source_too_long():
    long_source = "超长来源" * 60
    facts = parse_scout_facts(f"- 事实正文在这里（来源：{long_source}）")
    assert len(facts) == 1
    assert facts[0]["source"] == ""
    assert long_source in facts[0]["text"]


def test_plain_text_without_bullets_splits_by_line():
    raw = "事实甲的内容在这里可以判定\n事实乙的内容在这里可以判定"
    facts = parse_scout_facts(raw)
    assert [f["text"] for f in facts] == [
        "事实甲的内容在这里可以判定",
        "事实乙的内容在这里可以判定",
    ]


def test_single_blob_without_bullets_becomes_one_fact():
    raw = "只有一段没有分点的文字内容在这里"
    facts = parse_scout_facts(raw)
    assert facts == [{"text": "只有一段没有分点的文字内容在这里", "source": ""}]


def test_long_single_fact_body_is_preserved_intact():
    """上游 raw 已被截到 4000 字符；单条事实即使占满整段也必须完整保留，
    不得因单条上限而静默丢字（SCOUT_FACT_MAX_CHARS 与上游同值）。"""
    body = "长" * 3900
    facts = parse_scout_facts(body)
    assert len(facts) == 1
    assert facts[0]["text"] == body
    assert "…" not in facts[0]["text"]


def test_skips_leading_intro_line():
    raw = "以下是侦察到的事实：\n- 事实一的内容在这里\n- 事实二的内容在这里"
    facts = parse_scout_facts(raw)
    assert [f["text"] for f in facts] == [
        "事实一的内容在这里",
        "事实二的内容在这里",
    ]


def test_intro_line_kept_when_it_is_the_only_line():
    raw = "以下是侦察到的事实："
    facts = parse_scout_facts(raw)
    assert len(facts) == 1
    assert facts[0]["text"] == "以下是侦察到的事实："


def test_drops_empty_and_bullet_only_lines():
    raw = "- 有效事实内容在这里\n\n-\n   \n* 另一条有效事实内容"
    facts = parse_scout_facts(raw)
    assert [f["text"] for f in facts] == ["有效事实内容在这里", "另一条有效事实内容"]


def test_to_detail_reports_count_and_truncation():
    detail = to_detail("- 事实一的内容在这里\n- 事实二的内容在这里")
    assert detail["fact_count"] == 2
    assert detail["truncated"] is False
    assert len(detail["facts"]) == 2


def test_to_detail_truncates_beyond_item_cap():
    raw = "\n".join(f"- 事实编号{i}的内容在这里" for i in range(SCOUT_FACTS_MAX_ITEMS + 5))
    detail = to_detail(raw)
    assert len(detail["facts"]) == SCOUT_FACTS_MAX_ITEMS
    assert detail["fact_count"] == SCOUT_FACTS_MAX_ITEMS
    assert detail["truncated"] is True


def test_build_client_meta_json_shape():
    detail = to_detail("- 事实一的内容在这里（来源：X）")
    payload = build_client_meta_json(detail)
    assert payload is not None
    parsed = json.loads(payload)
    assert set(parsed) == {"scout_facts"}
    assert parsed["scout_facts"]["facts"] == [
        {"text": "事实一的内容在这里", "source": "X"}
    ]
    assert parsed["scout_facts"]["fact_count"] == 1


def test_build_client_meta_json_returns_none_for_empty_detail():
    assert build_client_meta_json(None) is None
    assert build_client_meta_json({}) is None
    assert build_client_meta_json({"facts": []}) is None
    assert build_client_meta_json({"facts": "not-a-list"}) is None


def test_build_client_meta_json_drops_oversized_payload():
    detail = {
        "facts": [{"text": "超长事实" * 5000, "source": ""}],
        "fact_count": 1,
        "truncated": False,
    }
    assert build_client_meta_json(detail) is None
    # 边界内仍可写入
    small = {"facts": [{"text": "短事实", "source": ""}], "fact_count": 1}
    assert build_client_meta_json(small) is not None
    assert SCOUT_CLIENT_META_MAX_BYTES == 32768
