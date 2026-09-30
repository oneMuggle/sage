"""UX-IA Round 2 · 批次 B：注入上下文统一预算。"""

from pathlib import Path

from backend.chat import project_context as pc
from backend.chat.context_budget import (
    KEEP_TOKENS,
    MIN_BUDGET_TOKENS,
    apply_context_budget,
    budget_for_window,
)
from backend.chat.context_sources import compute_context_sources
from backend.chat.env_context import build_environment_block
from backend.memory.working import estimate_tokens

BASE = "你是 Sage，一个办公助手。" * 40


def _head(materials_chars=0, sage_chars=200):
    parts = [BASE, pc.RENDER_HEADER + "\n" + "规" * sage_chars]
    if materials_chars:
        parts.append(pc.MATERIALS_HEADER + "\n" + "料" * materials_chars)
    parts.append("<available-skills>\n" + "- skill\n" * 50 + "</available-skills>")
    return "\n\n".join(parts)


def _sources(system, parts):
    msgs = [{"role": "system", "content": system}]
    msgs += [{"role": "system", "content": "\n\n".join(parts)}] if parts else []
    return {s["key"]: s["tokens"] for s in compute_context_sources(msgs)}


def test_budget_for_window():
    assert budget_for_window(None) is None
    assert budget_for_window(0) is None
    assert budget_for_window(4000) == MIN_BUDGET_TOKENS
    assert budget_for_window(128000) == int(128000 * 0.35)


def test_noop_when_under_budget_or_window_unknown():
    system, parts = _head(), [build_environment_block("/tmp/ws")]
    assert apply_context_budget(system, parts, 128000) == (system, parts, None)
    assert apply_context_budget(system, parts, None) == (system, parts, None)


def test_trims_lowest_priority_first_and_never_touches_base_or_env():
    env = build_environment_block("/tmp/ws")
    memory = "以下是相关的记忆上下文：\n" + "忆" * 3000
    system = _head(materials_chars=12000, sage_chars=800)
    new_sys, new_parts, report = apply_context_budget(system, [env, memory], 16000)

    assert report is not None
    assert report["after"] <= report["budget"]
    # 资料先被截；超出量足够时才轮到记忆
    assert "project_materials" in report["trimmed"]
    assert new_sys.startswith(BASE)  # 基础提示词原样
    assert new_parts[0] == env  # 环境信息原样
    assert "已按上下文预算截断" in new_sys
    # SAGE.md 优先级最高，本例中不应被截
    assert "sage_md" not in report["trimmed"]
    src = _sources(new_sys, new_parts)
    assert src["project_materials"] >= KEEP_TOKENS


def test_cascades_to_next_source_when_needed():
    memory = "以下是相关的记忆上下文：\n" + "忆" * 6000
    system = _head(materials_chars=6000)
    _, new_parts, report = apply_context_budget(system, [memory], 8000)
    assert set(report["trimmed"]) >= {"project_materials", "memory"}
    assert "已按上下文预算截断" in new_parts[0]


def test_closing_tag_preserved_when_skills_trimmed():
    skills = "<available-skills>\n" + "- 一个很长的技能描述\n" * 2000 + "</available-skills>"
    system = BASE + "\n\n" + skills
    new_sys, _, report = apply_context_budget(system, [], 4000)
    assert "skills" in report["trimmed"]
    assert new_sys.rstrip().endswith("</available-skills>")


def test_untrimmable_overflow_returns_unchanged():
    """只有基础提示词超预算时无块可截，原样返回。"""
    system = "基础" * 20000
    assert apply_context_budget(system, [], 4000) == (system, [], None)


def test_bad_input_is_fail_safe():
    assert apply_context_budget(None, [None], 4000)[2] is None  # type: ignore[arg-type]


def test_wired_into_legacy_stream_after_window_resolution():
    src = (Path(__file__).resolve().parents[3] / "api" / "legacy_routes.py").read_text(encoding="utf-8")
    win = src.index("effective_window = _resolve_effective_window(")
    call = src.index("apply_context_budget(", win)
    reserve = src.index("measure_request_reserve(", call)
    assert win < call < reserve
    assert estimate_tokens("x") >= 0
