"""UX-IA Round 2 · 批次 C：预算截断在来源明细中可见。"""

from backend.chat import project_context as pc
from backend.chat.context_breakdown import build_breakdown_snapshot
from backend.chat.context_budget import apply_context_budget
from backend.chat.context_sources import (
    TRIM_NOTE_FMT,
    compute_context_sources,
    trimmed_tokens_in,
)


def _by_key(sources):
    return {s["key"]: s for s in sources}


def test_trimmed_tokens_in_parses_notes():
    assert trimmed_tokens_in("") == 0
    assert trimmed_tokens_in("无截断") == 0
    text = "a" + TRIM_NOTE_FMT.format(n=120) + "b" + TRIM_NOTE_FMT.format(n=30)
    assert trimmed_tokens_in(text) == 150


def test_no_trimmed_field_without_truncation():
    head = "你是 Sage。\n\n" + pc.MATERIALS_HEADER + "\n" + "资料" * 50
    sources = _by_key(compute_context_sources([{"role": "system", "content": head}]))
    assert "trimmed" not in sources["project_materials"]


def test_budget_truncation_surfaces_in_sources():
    head = "\n\n".join(
        [
            "你是 Sage。" * 10,
            pc.RENDER_HEADER + "\n" + "规则" * 30,
            pc.MATERIALS_HEADER + "\n" + "资料内容很长。" * 3000,
        ]
    )
    new_head, _parts, report = apply_context_budget(head, [], 8000)
    assert report is not None
    assert report["trimmed"].get("project_materials", 0) > 0

    sources = _by_key(compute_context_sources([{"role": "system", "content": new_head}]))
    mat = sources["project_materials"]
    assert mat["trimmed"] > 0
    # 截断说明里的数字与预算报告同量级（说明文本自身占用少量 token）
    assert abs(mat["trimmed"] - report["trimmed"]["project_materials"]) < 64
    assert "trimmed" not in sources["sage_md"]


def test_snapshot_scales_trimmed_with_calibration():
    head = pc.MATERIALS_HEADER + "\n资料" + TRIM_NOTE_FMT.format(n=1000)
    msgs = [{"role": "system", "content": head}]
    est = build_breakdown_snapshot(msgs, None, None)
    base = _by_key(est["sources"])["project_materials"]["trimmed"]
    assert base == 1000
    total = est["estimated_total"]
    cal = build_breakdown_snapshot(msgs, None, total * 2)
    assert _by_key(cal["sources"])["project_materials"]["trimmed"] == 2000
