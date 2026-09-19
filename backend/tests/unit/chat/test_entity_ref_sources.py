"""R86: @memory:/@wiki: 实体引用命中 → 统一参考来源条目 单元测试

覆盖 backend/chat/entity_refs.py 新增能力：
- ResolvedRef.sources 结构化命中（wiki 带 path / memory 带 query 标题）
- collect_entity_sources 只收 memory/wiki（skill/agent 是执行者不入来源）
- process_with_sources 组合返回 (块, 来源)，畸形输入降级空值
"""

from __future__ import annotations

import pytest

from backend.chat.entity_refs import (
    EntityRef,
    ResolvedRef,
    collect_entity_sources,
    extract_entity_refs,
    process_with_sources,
)

pytestmark = pytest.mark.unit


def _ref(kind: str, query: str, sources=None, items=None, note=None) -> ResolvedRef:
    return ResolvedRef(
        ref=EntityRef(kind=kind, query=query, raw=f"@{kind}:{query}"),
        items=items or [],
        note=note,
        sources=sources or [],
    )


def test_collect_flattens_memory_and_wiki_hits():
    resolved = [
        _ref("memory", "火锅", sources=[{"kind": "memory", "title": "@memory:火锅 [episodic]", "snippet": "爱吃火锅"}]),
        _ref("wiki", "架构", sources=[{"kind": "wiki", "title": "架构", "path": "wiki/arch.md", "snippet": "分层"}]),
    ]
    out = collect_entity_sources(resolved)
    assert [s["kind"] for s in out] == ["memory", "wiki"]
    assert out[1]["path"] == "wiki/arch.md"


def test_collect_skips_skill_agent_and_malformed():
    resolved = [
        _ref("skill", "pdf", sources=[{"kind": "tool", "tool": "x"}]),
        _ref("agent", "研究", sources=[{"kind": "wiki", "title": "bad"}]),
        _ref("wiki", "rust", sources=["not-a-dict", {"kind": "wiki", "path": "wiki/rust.md"}]),
    ]
    out = collect_entity_sources(resolved)
    # agent/skill 的 ResolvedRef 整体跳过（ref.kind 过滤）——它们是执行者而非参考资料
    assert out == [{"kind": "wiki", "path": "wiki/rust.md"}]


def test_extract_and_process_empty_text():
    assert extract_entity_refs("没有引用的消息") == []
    block, sources = process_with_sources("没有引用的消息")
    assert block == ""
    assert sources == []


def test_process_with_sources_degrades_on_error(monkeypatch):
    import backend.chat.entity_refs as er

    def boom(text, session_id=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(er, "extract_entity_refs", boom)
    block, sources = process_with_sources("@wiki:x", session_id="s1")
    assert block == ""
    assert sources == []


def test_resolve_wiki_populates_sources(monkeypatch):
    from types import SimpleNamespace

    import backend.chat.entity_refs as er

    monkeypatch.setattr(er, "_wiki_project_root", lambda: object.__class__ and _FakeRoot())
    hits = [
        SimpleNamespace(title="架构", path="wiki/arch.md", snippet="分层设计"),
        SimpleNamespace(title=None, path="wiki/x.md", snippet="无标题跳过"),
    ]

    class _FakeSearchResp:
        results = hits

    monkeypatch.setattr("backend.wiki.search.search_wiki", lambda root, q, limit: _FakeSearchResp())

    resolved = er.resolve_entity_refs([EntityRef("wiki", "架构", "@wiki:架构")], session_id="s1")
    sources = collect_entity_sources(resolved)
    assert len(sources) == 1
    assert sources[0] == {"kind": "wiki", "title": "架构", "path": "wiki/arch.md", "snippet": "分层设计"}


class _FakeRoot:
    name = "fake-wiki"
    is_dir = lambda self: True  # noqa: E731


def test_resolve_memory_populates_sources(monkeypatch):
    import backend.chat.entity_refs as er

    class _FakeMM:
        def search_memories(self, query, memory_type=None, limit=5, session_id=None):
            return [
                {"content": "爱吃火锅", "memory_type": "episodic"},
                {"summary": "", "content": None},  # 无内容 → 跳过
                {"content": "项目代号 Sage", "memory_type": "semantic"},
            ]

    monkeypatch.setattr(
        "backend.memory.get_memory_manager", lambda: _FakeMM()
    )
    resolved = er.resolve_entity_refs([EntityRef("memory", "火锅", "@memory:火锅")], session_id="s1")
    sources = collect_entity_sources(resolved)
    assert len(sources) == 2
    assert sources[0]["title"] == "@memory:火锅 [episodic]"
    assert sources[0]["snippet"] == "爱吃火锅"
    assert sources[1]["title"] == "@memory:火锅 [semantic]"
