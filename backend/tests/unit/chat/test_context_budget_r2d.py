"""UX-IA Round 2 · 批次 D：相关度截断、hex 路径接入、技能自动激活块标记。"""

from types import SimpleNamespace

from backend.application.services.chat_service import ChatService
from backend.chat import project_context as pc
from backend.chat.context_budget import apply_context_budget
from backend.chat.context_sources import compute_context_sources


def _by_key(sources):
    return {s["key"]: s for s in sources}


def _materials(entries):
    return pc.MATERIALS_HEADER + "\n" + "\n\n".join(entries)


def test_relevance_keeps_matching_entry_even_if_last():
    filler = ["无关资料段落。" * 400 for _ in range(4)]
    target = "数据库迁移步骤：先备份 sqlite，再执行 alembic upgrade。"
    head = "你是 Sage。\n\n" + _materials(filler + [target])
    new_head, _, report = apply_context_budget(head, [], 8000, "sqlite 数据库迁移怎么做")
    assert report is not None
    assert target in new_head
    assert "已按上下文预算截断约" in new_head


def test_without_query_falls_back_to_head_truncation():
    filler = ["无关资料段落。" * 400 for _ in range(4)]
    target = "数据库迁移步骤：先备份 sqlite。"
    head = "你是 Sage。\n\n" + _materials(filler + [target])
    new_head, _, report = apply_context_budget(head, [], 8000)
    assert report is not None
    assert target not in new_head


def test_irrelevant_query_falls_back_to_head_truncation():
    head = "你是 Sage。\n\n" + _materials(["甲" * 3000, "乙" * 3000, "丙" * 3000])
    new_head, _, report = apply_context_budget(head, [], 8000, "zzqq")
    assert report is not None
    assert new_head.startswith("你是 Sage。")


def test_hex_memory_prefix_and_activated_skills_are_recognised():
    text = (
        "你是 Sage。"
        + "\n\n以下是相关的记忆上下文:\n- 用户喜欢简洁"
        + "\n\n以下是根据用户本次消息自动激活的技能指令 (A16 Skill Auto-Activation):\n技能正文"
    )
    sources = _by_key(compute_context_sources([{"role": "system", "content": text}]))
    assert "memory" in sources
    assert "skills_activated" in sources
    assert "other_dynamic" not in sources


def test_chat_service_budget_hook():
    big = "你是 Sage。\n\n" + _materials(["资料内容很长。" * 3000])
    fake = SimpleNamespace(_context_window_resolver=None)
    assert ChatService._apply_context_budget(fake, big, "q") == big

    fake.__dict__["_context_window_resolver"] = lambda: 8000
    out = ChatService._apply_context_budget(fake, big, "q")
    assert len(out) < len(big)
    assert "已按上下文预算截断约" in out

    def boom():
        raise RuntimeError("x")

    fake.__dict__["_context_window_resolver"] = boom
    assert ChatService._apply_context_budget(fake, big, "q") == big


def test_main_wires_resolver():
    import inspect

    from backend import main

    assert "context_window_resolver=_resolve_default_context_window" in inspect.getsource(main)
