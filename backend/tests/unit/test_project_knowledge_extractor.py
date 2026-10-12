"""ProjectKnowledgeExtractor 单元测试 (M2, 2026-10-12)。

覆盖:
- ProposedKnowledgeEntry / ExtractionResult dataclass
- _build_prompt()
- _parse_response(): 有效 JSON / markdown 包裹 / 无效 JSON / 空响应 / entries 非列表
- _parse_entry(): 正常 / 无效 category 降级 / importance 裁剪 / content 截断 / 无 content 跳过
- confirm(): 写入 store / 空 content 跳过 / invalidate 调用
- extract(): LLM 调用 + 空消息 + not available + LLM failure
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.project_knowledge_extractor import (
    ExtractionResult,
    ProposedKnowledgeEntry,
    ProjectKnowledgeExtractor,
)

pytestmark = [pytest.mark.unit]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=json.dumps(
            {
                "reasoning": "对话中讨论了架构决策",
                "entries": [
                    {
                        "content": "项目使用 JWT + Redis 黑名单方案做 token 失效",
                        "category": "decision",
                        "importance": 8,
                        "source_message_ids": ["msg_abc", "msg_def"],
                        "reasoning": "用户和助手讨论了 token 失效方案",
                    },
                    {
                        "content": "前端使用 Tailwind CSS 作为样式方案",
                        "category": "convention",
                        "importance": 6,
                        "source_message_ids": ["msg_ghi"],
                    },
                ],
            }
        )
    )
    return llm


@pytest.fixture()
def extractor(mock_llm):
    return ProjectKnowledgeExtractor(llm_client=mock_llm)


@pytest.fixture()
def mock_project():
    p = MagicMock()
    p.project_type = "coding"
    p.description = "A coding project"
    p.path = "/tmp/test-project"
    return p


# ── ProposedKnowledgeEntry ───────────────────────────────────────────────────


class TestProposedKnowledgeEntry:
    def test_to_dict(self):
        entry = ProposedKnowledgeEntry(
            content="Test knowledge",
            category="decision",
            importance=8,
            source_message_ids=["msg1", "msg2"],
            reasoning="important decision",
        )
        d = entry.to_dict()
        assert d == {
            "content": "Test knowledge",
            "category": "decision",
            "importance": 8,
            "source_message_ids": ["msg1", "msg2"],
            "reasoning": "important decision",
        }

    def test_defaults(self):
        entry = ProposedKnowledgeEntry(content="Test")
        assert entry.category == "convention"
        assert entry.importance == 5
        assert entry.source_message_ids == []
        assert entry.reasoning is None


# ── ExtractionResult ─────────────────────────────────────────────────────────


class TestExtractionResult:
    def test_to_preview(self):
        result = ExtractionResult(
            entries=[
                ProposedKnowledgeEntry(
                    content="A", category="decision", importance=8
                ),
                ProposedKnowledgeEntry(
                    content="B", category="convention", importance=5
                ),
            ]
        )
        preview = result.to_preview()
        assert len(preview) == 2
        assert preview[0]["content"] == "A"
        assert preview[1]["content"] == "B"

    def test_defaults(self):
        result = ExtractionResult(entries=[])
        assert result.reasoning == ""
        assert result.tokens_used == 0
        assert result.raw_json is None


# ── _parse_response() ─────────────────────────────────────────────────────────


class TestParseResponse:
    def test_valid_json(self, extractor):
        raw = json.dumps(
            {
                "reasoning": "test",
                "entries": [
                    {"content": "Knowledge A", "category": "decision"},
                    {"content": "Knowledge B", "category": "convention"},
                ],
            }
        )
        result = extractor._parse_response(raw)
        assert len(result.entries) == 2
        assert result.entries[0].content == "Knowledge A"
        assert result.reasoning == "test"

    def test_markdown_code_block(self, extractor):
        raw = (
            "```json\n"
            '{"reasoning": "ok", "entries": [{"content": "X"}]}\n'
            "```"
        )
        result = extractor._parse_response(raw)
        assert len(result.entries) == 1
        assert result.entries[0].content == "X"

    def test_markdown_code_block_no_lang(self, extractor):
        raw = (
            "```\n"
            '{"reasoning": "ok", "entries": [{"content": "Y"}]}\n'
            "```"
        )
        result = extractor._parse_response(raw)
        assert len(result.entries) == 1

    def test_json_with_surrounding_text(self, extractor):
        raw = (
            "Analysis:\n"
            '{"reasoning": "ok", "entries": [{"content": "Z"}]}\n'
            "Done."
        )
        result = extractor._parse_response(raw)
        assert len(result.entries) == 1

    def test_invalid_json_returns_empty(self, extractor):
        result = extractor._parse_response("not json at all")
        assert result.entries == []
        assert "无法解析" in result.reasoning or "格式错误" in result.reasoning

    def test_empty_response(self, extractor):
        result = extractor._parse_response("")
        assert result.entries == []
        assert "空响应" in result.reasoning

    def test_none_response(self, extractor):
        result = extractor._parse_response(None)
        assert result.entries == []

    def test_entries_not_list(self, extractor):
        raw = json.dumps({"reasoning": "test", "entries": "not a list"})
        result = extractor._parse_response(raw)
        assert result.entries == []
        assert "不是列表" in result.reasoning


# ── _parse_entry() ───────────────────────────────────────────────────────────


class TestParseEntry:
    def test_valid_entry(self, extractor):
        data = {
            "content": "Knowledge content",
            "category": "architecture",
            "importance": 7,
            "source_message_ids": ["msg1"],
            "reasoning": "important",
        }
        entry = extractor._parse_entry(data)
        assert entry is not None
        assert entry.content == "Knowledge content"
        assert entry.category == "architecture"
        assert entry.importance == 7

    def test_invalid_category_defaults(self, extractor):
        data = {"content": "test", "category": "invalid_category"}
        entry = extractor._parse_entry(data)
        assert entry is not None
        assert entry.category == "convention"

    def test_importance_clamped_high(self, extractor):
        data = {"content": "test", "importance": 15}
        entry = extractor._parse_entry(data)
        assert entry is not None
        assert entry.importance == 10

    def test_importance_clamped_low(self, extractor):
        data = {"content": "test", "importance": -5}
        entry = extractor._parse_entry(data)
        assert entry is not None
        assert entry.importance == 1

    def test_importance_invalid_defaults(self, extractor):
        data = {"content": "test", "importance": "not a number"}
        entry = extractor._parse_entry(data)
        assert entry is not None
        assert entry.importance == 5

    def test_content_truncated(self, extractor):
        data = {"content": "x" * 500}
        entry = extractor._parse_entry(data)
        assert entry is not None
        assert len(entry.content) == 200

    def test_no_content_skipped(self, extractor):
        data = {"category": "decision"}
        entry = extractor._parse_entry(data)
        assert entry is None

    def test_empty_content_skipped(self, extractor):
        data = {"content": "", "category": "decision"}
        entry = extractor._parse_entry(data)
        assert entry is None

    def test_non_dict_skipped(self, extractor):
        entry = extractor._parse_entry("not a dict")
        assert entry is None

    def test_source_message_ids_non_list(self, extractor):
        data = {"content": "test", "source_message_ids": "not a list"}
        entry = extractor._parse_entry(data)
        assert entry is not None
        assert entry.source_message_ids == []

    def test_source_message_ids_filtered(self, extractor):
        data = {
            "content": "test",
            "source_message_ids": ["msg1", None, "", "msg2"],
        }
        entry = extractor._parse_entry(data)
        assert entry is not None
        assert entry.source_message_ids == ["msg1", "msg2"]


# ── confirm() ─────────────────────────────────────────────────────────────────


class TestConfirm:
    def test_confirm_creates_entries(self, extractor):
        mock_store = MagicMock()
        mock_store.add = MagicMock(side_effect=["id1", "id2"])
        mock_store.invalidate = MagicMock()

        with patch(
            "backend.memory.project_profile.get_project_profile",
            return_value=mock_store,
        ):
            result = extractor.confirm(
                project_key="/tmp/test",
                entries=[
                    {"content": "A", "category": "decision", "importance": 8},
                    {"content": "B", "category": "convention", "importance": 5},
                ],
            )

        assert result["created"] == 2
        assert result["skipped"] == 0
        assert result["ids"] == ["id1", "id2"]
        assert mock_store.add.call_count == 2
        mock_store.invalidate.assert_called_once_with("/tmp/test")

    def test_confirm_skips_empty_content(self, extractor):
        mock_store = MagicMock()
        mock_store.add = MagicMock(return_value="id1")
        mock_store.invalidate = MagicMock()

        with patch(
            "backend.memory.project_profile.get_project_profile",
            return_value=mock_store,
        ):
            result = extractor.confirm(
                project_key="/tmp/test",
                entries=[
                    {"content": "Valid", "category": "decision"},
                    {"content": "", "category": "decision"},
                    {"content": "   ", "category": "decision"},
                ],
            )

        assert result["created"] == 1
        assert result["skipped"] == 2
        assert mock_store.add.call_count == 1

    def test_confirm_skips_failed_add(self, extractor):
        mock_store = MagicMock()
        mock_store.add = MagicMock(side_effect=["id1", None])
        mock_store.invalidate = MagicMock()

        with patch(
            "backend.memory.project_profile.get_project_profile",
            return_value=mock_store,
        ):
            result = extractor.confirm(
                project_key="/tmp/test",
                entries=[
                    {"content": "A", "category": "decision"},
                    {"content": "B", "category": "decision"},
                ],
            )

        assert result["created"] == 1
        assert result["skipped"] == 1


# ── _build_prompt() ──────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_contains_project_info(self, extractor, mock_project):
        messages = [{"id": "m1", "role": "user", "content": "hello"}]
        prompt = extractor._build_prompt(
            project=mock_project,
            messages=messages,
            existing_entries=[],
        )
        assert "coding" in prompt
        assert "A coding project" in prompt

    def test_contains_messages(self, extractor, mock_project):
        messages = [
            {"id": "m1", "role": "user", "content": "用户问题"},
            {"id": "m2", "role": "assistant", "content": "助手回答"},
        ]
        prompt = extractor._build_prompt(
            project=mock_project,
            messages=messages,
            existing_entries=[],
        )
        assert "用户问题" in prompt
        assert "助手回答" in prompt
        assert "[用户]" in prompt
        assert "[助手]" in prompt

    def test_contains_existing_entries(self, extractor, mock_project):
        existing = [
            {"category": "decision", "content": "已有知识A"},
            {"category": "convention", "content": "已有知识B"},
        ]
        prompt = extractor._build_prompt(
            project=mock_project,
            messages=[{"id": "m1", "role": "user", "content": "test"}],
            existing_entries=existing,
        )
        assert "已有知识A" in prompt
        assert "已有知识B" in prompt
        assert "避免重复" in prompt


# ── extract() integration ────────────────────────────────────────────────────


class TestExtract:
    @pytest.mark.asyncio
    async def test_extract_calls_llm(self, extractor, mock_llm):
        with (
            patch.object(
                extractor, "_load_project", return_value=MagicMock(
                    project_type="coding",
                    description="test",
                    path="/tmp/test",
                )
            ),
            patch.object(
                extractor, "_load_messages",
                return_value=[{"id": "m1", "role": "user", "content": "hi"}],
            ),
            patch.object(
                extractor, "_get_existing_profile_entries", return_value=[]
            ),
        ):
            result = await extractor.extract(
                project_id="proj-1",
                session_id="session-1",
            )

        mock_llm.complete.assert_called_once()
        assert len(result.entries) > 0
        assert result.raw_json is not None

    @pytest.mark.asyncio
    async def test_extract_empty_messages(self, extractor):
        with (
            patch.object(
                extractor, "_load_project", return_value=MagicMock(
                    project_type="coding",
                    description="test",
                    path="/tmp/test",
                )
            ),
            patch.object(
                extractor, "_load_messages", return_value=[]
            ),
        ):
            result = await extractor.extract(
                project_id="proj-1",
                session_id="session-1",
            )

        assert result.entries == []
        assert "没有可分析的消息" in result.reasoning

    @pytest.mark.asyncio
    async def test_extract_not_available(self):
        extractor = ProjectKnowledgeExtractor(llm_client=None)
        extractor._llm = None
        with pytest.raises(RuntimeError, match="不可用"):
            await extractor.extract(
                project_id="proj-1",
                session_id="session-1",
            )

    @pytest.mark.asyncio
    async def test_extract_llm_failure(self, extractor):
        extractor._llm.complete = AsyncMock(
            side_effect=Exception("LLM timeout")
        )
        with (
            patch.object(
                extractor, "_load_project", return_value=MagicMock(
                    project_type="coding",
                    description="test",
                    path="/tmp/test",
                )
            ),
            patch.object(
                extractor, "_load_messages",
                return_value=[{"id": "m1", "role": "user", "content": "hi"}],
            ),
            patch.object(
                extractor, "_get_existing_profile_entries", return_value=[]
            ),
        ):
            with pytest.raises(RuntimeError, match="LLM 调用失败"):
                await extractor.extract(
                    project_id="proj-1",
                    session_id="session-1",
                )
