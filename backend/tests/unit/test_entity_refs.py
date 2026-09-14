"""对标 S3：@memory:/@wiki:/@skill:/@agent: 实体引用解析。"""

from unittest.mock import patch

import pytest

from backend.chat import entity_refs
from backend.chat.entity_refs import (
    EntityRef,
    ResolvedRef,
    extract_entity_refs,
    render_references_block,
)

pytestmark = pytest.mark.unit


class TestExtract:
    def test_basic_kinds(self):
        refs = extract_entity_refs("看看 @memory:火锅 和 @wiki:量子纠缠，用 @skill:pdf-reader，交给 @agent:researcher")
        assert [(r.kind, r.query) for r in refs] == [
            ("memory", "火锅"),
            ("wiki", "量子纠缠"),
            ("skill", "pdf-reader"),
            ("agent", "researcher"),
        ]

    def test_dedupe_and_ignore_plain_at(self):
        refs = extract_entity_refs("@memory:a @memory:a @foo.docx email@memory:b @unknown:x")
        assert [(r.kind, r.query) for r in refs] == [("memory", "a")]

    def test_empty_query_ignored(self):
        assert extract_entity_refs("@memory: 什么") == []
        assert extract_entity_refs("") == []


class TestRender:
    def test_empty(self):
        assert render_references_block([]) == ""

    def test_items_and_note(self):
        out = render_references_block(
            [
                ResolvedRef(EntityRef("memory", "火锅", "@memory:火锅"), items=["[episodic] 用户喜欢火锅"]),
                ResolvedRef(EntityRef("wiki", "x", "@wiki:x"), note="尚未打开任何 Wiki 项目"),
            ]
        )
        assert out.startswith("<references>")
        assert out.endswith("</references>")
        assert "=== 记忆: 火锅 ===" in out
        assert "- [episodic] 用户喜欢火锅" in out
        assert "=== Wiki: x ===" in out
        assert "（尚未打开任何 Wiki 项目）" in out

    def test_budget(self):
        big = ResolvedRef(EntityRef("memory", "q", "@memory:q"), items=["x" * 600] * 5)
        out = render_references_block([big, big, big])
        assert len(out) <= entity_refs.MAX_BLOCK_CHARS + 200
        assert "已省略" in out


class TestResolvers:
    def test_memory_uses_manager(self):
        class FakeMM:
            def search_memories(self, query, memory_type=None, limit=5, session_id=None):
                assert query == "火锅"
                return [{"content": "用户喜欢火锅", "memory_type": "episodic"}, {"summary": "", "content": ""}]

        with patch("backend.memory.get_memory_manager", return_value=FakeMM()):
            r = entity_refs._resolve_memory("火锅", "s1")
        assert r.items == ["[episodic] 用户喜欢火锅"]
        assert r.note is None

    def test_memory_failure_is_note(self):
        with patch("backend.memory.get_memory_manager", side_effect=RuntimeError("boom")):
            r = entity_refs._resolve_memory("x", None)
        assert r.items == []
        assert r.note

    def test_wiki_without_project(self):
        with patch.object(entity_refs, "_wiki_project_root", return_value=None):
            r = entity_refs._resolve_wiki("x", None)
        assert "Wiki" in (r.note or "")

    def test_agent_match_by_name_or_id(self):
        rows = [
            {"id": "researcher", "name": "研究员", "description": "查资料", "system_prompt": "你是研究员", "tools": ["web_search"]},
            {"id": "coder", "name": "程序员", "description": "写代码", "system_prompt": "", "tools": []},
        ]
        with patch("backend.data.agent_repo.AgentRepository") as repo:
            repo.return_value.list_all.return_value = rows
            r = entity_refs._resolve_agent("研究", None)
        assert len(r.items) == 1
        assert "研究员 (researcher)" in r.items[0]
        assert "web_search" in r.items[0]

    def test_process_end_to_end_with_failures(self):
        # 所有数据源都坏掉 → 仍然产出块（带说明），不抛
        # NOTE(win7): 括号多行 with 是 Python 3.10+ 语法，Win7 CI 跑 3.8，改为嵌套写法。
        with patch("backend.memory.get_memory_manager", side_effect=RuntimeError), patch.object(
            entity_refs, "_wiki_project_root", return_value=None
        ), patch("backend.data.agent_repo.AgentRepository", side_effect=RuntimeError):
            out = entity_refs.process("@memory:a @wiki:b @agent:c", "s1")
        assert "<references>" in out
        assert "=== 记忆: a ===" in out
        assert "=== Wiki: b ===" in out
        assert "=== 智能体: c ===" in out

    def test_process_no_refs(self):
        assert entity_refs.process("普通消息 @file.docx") == ""
