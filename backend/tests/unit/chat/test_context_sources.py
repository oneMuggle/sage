"""UX-IA Round 2 · 本轮注入上下文来源明细。"""

from backend.chat import project_context as pc
from backend.chat.context_breakdown import build_breakdown_snapshot
from backend.chat.context_sources import compute_context_sources
from backend.chat.env_context import build_environment_block


def _by_key(sources):
    return {s["key"]: s for s in sources}


def test_markers_match_real_builder_headers():
    """标记与真实构造函数的标题保持同步（改标题时本测试会失败）。"""
    from backend.chat.context_sources import SOURCE_MARKERS

    markers = {m for _, m, _ in SOURCE_MARKERS}
    for header in (
        pc.RENDER_HEADER,
        pc.METADATA_HEADER,
        pc.MATERIALS_HEADER,
        pc.CONSTRAINTS_HEADER,
    ):
        assert header in markers
    assert build_environment_block("/tmp/ws").startswith("<environment>")


def test_splits_head_and_trailing_system_by_source():
    head = "\n\n".join(
        [
            "你是 Sage。" * 20,
            pc.RENDER_HEADER + "\n" + "规则" * 50,
            pc.METADATA_HEADER + "\n项目说明",
            pc.MATERIALS_HEADER + "\n" + "资料" * 80,
            "<available-skills>\n- a\n- b\n</available-skills>",
        ]
    )
    trailing = "\n\n".join(
        [
            build_environment_block("/tmp/ws"),
            "技能自动激活：写作规范" * 5,
            "以下是相关的记忆上下文：\n- 用户喜欢简洁",
        ]
    )
    messages = [
        {"role": "system", "content": head},
        {"role": "user", "content": "旧问题"},
        {"role": "system", "content": trailing},
        {"role": "user", "content": "新问题"},
    ]
    src = _by_key(compute_context_sources(messages))
    for key in (
        "base_system",
        "sage_md",
        "project_overview",
        "project_materials",
        "skills",
        "environment",
        "memory",
        "other_dynamic",
    ):
        assert src[key]["tokens"] > 0, key
    assert "attachments" not in src
    assert src["project_materials"]["tokens"] > src["project_overview"]["tokens"]
    # 用户消息不计入来源
    assert sum(s["tokens"] for s in src.values()) < 2000


def test_closing_tag_stops_block_and_rest_is_other_dynamic():
    text = "<environment>\n- 日期\n</environment>\n\n" + "未标记块" * 30
    src = _by_key(compute_context_sources([{"role": "system", "content": "s"}, {"role": "system", "content": text}]))
    assert src["other_dynamic"]["tokens"] > src["environment"]["tokens"]


def test_nested_attached_documents_counted_once():
    block = (
        "<attachments>\n<attached_document id='a'>x</attached_document>\n"
        "<attached_document id='b'>y</attached_document>\n</attachments>"
    )
    src = _by_key(compute_context_sources([{"role": "system", "content": "s"}, {"role": "system", "content": block}]))
    assert src["attachments"]["count"] == 1
    assert "other_dynamic" not in src


def test_multimodal_and_empty_inputs():
    assert compute_context_sources([]) == []
    msgs = [{"role": "system", "content": [{"type": "text", "text": pc.RENDER_HEADER + "\nabc"}]}]
    assert _by_key(compute_context_sources(msgs))["sage_md"]["tokens"] > 0


def test_snapshot_includes_scaled_sources():
    msgs = [
        {"role": "system", "content": pc.RENDER_HEADER + "\n" + "规则" * 100},
        {"role": "user", "content": "hi"},
    ]
    raw = build_breakdown_snapshot(msgs, None, None)
    scaled = build_breakdown_snapshot(msgs, None, raw["estimated_total"] * 2)
    assert raw["sources"][0]["key"] == "sage_md"
    assert scaled["calibrated"] is True
    ratio = scaled["sources"][0]["tokens"] / raw["sources"][0]["tokens"]
    assert 1.9 < ratio < 2.1
