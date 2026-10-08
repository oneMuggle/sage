"""UX-IA Round 2 · 本轮注入上下文来源明细。"""

from backend.chat import project_context as pc
from backend.chat.context_breakdown import build_breakdown_snapshot
from backend.chat.context_sources import (
    MAX_ITEMS_PER_SOURCE,
    compute_context_sources,
    excluded_items,
    source_items,
)
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


# ── C1 细粒度来源追溯：只提取 payload 中真实存在的标识 ──────────────────


def test_material_items_carry_real_ids_and_truncation_flag():
    block = "\n".join(
        [
            pc.MATERIALS_HEADER,
            "以下是用户显式添加的参考资料。",
            "--- 4ddd271f-1764-4553-bd19-a12724cdf2b1 [ready] ---",
            "完整资料内容" * 20,
            "--- 9f0c2a11-2233-4455-6677-8899aabbccdd [ready] (来源消息 msg_7) ---",
            "被截断的资料内容" * 20 + " [截断]",
        ]
    )
    src = _by_key(compute_context_sources([{"role": "system", "content": block}]))
    items = src["project_materials"]["items"]
    assert [i["id"] for i in items] == [
        "4ddd271f-1764-4553-bd19-a12724cdf2b1",
        "9f0c2a11-2233-4455-6677-8899aabbccdd",
    ]
    assert items[0]["truncated"] is False
    assert items[1]["truncated"] is True
    assert "来源消息 msg_7" in items[1]["label"]
    assert src["project_materials"]["identifiable"] is True


def test_excluded_materials_are_reported_not_invented():
    block = "\n".join(
        [
            pc.MATERIALS_HEADER,
            "--- aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee [ready] ---",
            "资料",
            "另有 3 条资料超出预算被排除。",
        ]
    )
    src = _by_key(compute_context_sources([{"role": "system", "content": block}]))
    assert src["project_materials"]["excluded"] == 3
    assert len(src["project_materials"]["items"]) == 1


def test_skill_and_attachment_items_use_declared_names():
    skills = "<available-skills>\n- /search：搜索\n- /writer：写作\n</available-skills>"
    activated = (
        "以下是根据用户本次消息自动激活的技能指令 (A16 Skill Auto-Activation):\n\n"
        "Skill 'report-writing' auto-activated: 写报告"
    )
    attachments = "<attachments>\n=== docs/spec.md ===\n摘要\n</attachments>"
    src = _by_key(
        compute_context_sources(
            [{"role": "system", "content": "s"}, {"role": "system", "content": "\n\n".join([skills, activated, attachments])}]
        )
    )
    assert [i["id"] for i in src["skills"]["items"]] == ["search", "writer"]
    assert [i["id"] for i in src["skills_activated"]["items"]] == ["report-writing"]
    assert [i["id"] for i in src["attachments"]["items"]] == ["docs/spec.md"]


def test_memory_source_is_marked_not_identifiable():
    block = "以下是相关的记忆上下文：\n- 用户偏好简洁\n- 项目用 Python 3.8"
    src = _by_key(compute_context_sources([{"role": "system", "content": "s"}, {"role": "system", "content": block}]))
    assert src["memory"]["identifiable"] is False
    assert "items" not in src["memory"]


def test_items_are_capped_with_omitted_count():
    lines = [pc.MATERIALS_HEADER]
    for i in range(MAX_ITEMS_PER_SOURCE + 3):
        lines.append(f"--- mat-{i:032x} [ready] ---")
        lines.append("内容")
    src = _by_key(compute_context_sources([{"role": "system", "content": "\n".join(lines)}]))
    entry = src["project_materials"]
    assert len(entry["items"]) == MAX_ITEMS_PER_SOURCE
    assert entry["omitted_items"] == 3


def test_source_items_helpers_return_empty_for_unknown_sources():
    assert source_items("memory", "- 记忆条目") == []
    assert source_items("project_overview", "项目说明") == []
    assert excluded_items("project_materials", "另有 2 条资料超出预算被排除。") == 2
    assert excluded_items("skills", "另有 2 条资料超出预算被排除。") == 0
