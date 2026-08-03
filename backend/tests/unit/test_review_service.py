"""Tests for ReviewService with LLM-driven skill draft generation."""

import json
import time
from unittest.mock import AsyncMock, Mock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_turn(text: str) -> Mock:
    """Create a mock AssistantTurn with the given text content."""
    turn = Mock()
    turn.text = text
    return turn


def _make_mock_provider(response_text: str) -> Mock:
    """Create a mock LLM provider whose complete() returns *response_text*."""
    provider = Mock()
    provider.complete = AsyncMock(return_value=_make_mock_turn(response_text))
    return provider


VALID_LLM_OUTPUT = json.dumps(
    {
        "name": "test-skill",
        "description": "A test skill",
        "when_to_use": "When testing",
        "content": "# Test Skill\n\n## Steps\n\n1. Test",
    }
)


# ---------------------------------------------------------------------------
# Tests: generate_draft happy path
# ---------------------------------------------------------------------------


class TestGenerateDraftHappyPath:
    """Core happy-path tests for ReviewService.generate_draft."""

    @pytest.mark.asyncio()
    async def test_generate_draft_with_mock_llm(self):
        """generate_draft returns a SkillDraft with fields parsed from LLM JSON."""
        from backend.skills.review_service import ReviewService, SkillDraft

        provider = _make_mock_provider(VALID_LLM_OUTPUT)
        service = ReviewService(provider)

        draft = await service.generate_draft(
            trigger_type="complex_turn",
            context={"tool_calls": [{"tool": "read", "args": {"path": "/a"}}]},
        )

        assert isinstance(draft, SkillDraft)
        assert draft.name == "test-skill"
        assert draft.description == "A test skill"
        assert draft.trigger_type == "complex_turn"
        assert draft.when_to_use == "When testing"
        assert "# Test Skill" in draft.content
        assert draft.status == "pending"
        assert draft.id  # non-empty UUID string
        assert draft.created_at > 0

    @pytest.mark.asyncio()
    async def test_generate_draft_preserves_source_context(self):
        """Source session_id and context are carried through to the draft."""
        from backend.skills.review_service import ReviewService

        provider = _make_mock_provider(VALID_LLM_OUTPUT)
        service = ReviewService(provider)

        ctx = {"session_id": "sess-42", "tool_calls": []}
        draft = await service.generate_draft(trigger_type="complex_turn", context=ctx)

        assert draft.source_session_id == "sess-42"
        assert draft.source_context == ctx

    @pytest.mark.asyncio()
    async def test_generate_draft_default_session_id_empty(self):
        """Missing session_id in context defaults to empty string."""
        from backend.skills.review_service import ReviewService

        provider = _make_mock_provider(VALID_LLM_OUTPUT)
        service = ReviewService(provider)

        draft = await service.generate_draft(
            trigger_type="repeated_pattern", context={}
        )
        assert draft.source_session_id == ""


# ---------------------------------------------------------------------------
# Tests: LLM output parsing
# ---------------------------------------------------------------------------


class TestParseLLMOutput:
    """Tests for JSON extraction from various LLM output formats."""

    @pytest.mark.asyncio()
    async def test_parse_markdown_json_code_block(self):
        """LLM wraps JSON in ```json ... ``` — should be extracted."""
        from backend.skills.review_service import ReviewService

        wrapped = f"Here is the result:\n```json\n{VALID_LLM_OUTPUT}\n```\nDone!"
        provider = _make_mock_provider(wrapped)
        service = ReviewService(provider)

        draft = await service.generate_draft(trigger_type="t", context={})
        assert draft.name == "test-skill"

    @pytest.mark.asyncio()
    async def test_parse_plain_markdown_code_block(self):
        """LLM wraps JSON in ``` ... ``` (no language tag) — should work."""
        from backend.skills.review_service import ReviewService

        wrapped = f"```\n{VALID_LLM_OUTPUT}\n```"
        provider = _make_mock_provider(wrapped)
        service = ReviewService(provider)

        draft = await service.generate_draft(trigger_type="t", context={})
        assert draft.name == "test-skill"

    @pytest.mark.asyncio()
    async def test_parse_raw_json(self):
        """LLM returns bare JSON — should parse directly."""
        from backend.skills.review_service import ReviewService

        provider = _make_mock_provider(VALID_LLM_OUTPUT)
        service = ReviewService(provider)

        draft = await service.generate_draft(trigger_type="t", context={})
        assert draft.name == "test-skill"

    @pytest.mark.asyncio()
    async def test_parse_json_with_surrounding_text(self):
        """LLM adds explanatory text around the JSON block."""
        from backend.skills.review_service import ReviewService

        output = f"Sure!\n```json\n{VALID_LLM_OUTPUT}\n```\nLet me know."
        provider = _make_mock_provider(output)
        service = ReviewService(provider)

        draft = await service.generate_draft(trigger_type="t", context={})
        assert draft.name == "test-skill"


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """LLM errors must be handled gracefully."""

    @pytest.mark.asyncio()
    async def test_invalid_json_raises_value_error(self):
        """LLM returning non-JSON output raises ValueError."""
        from backend.skills.review_service import ReviewService

        provider = _make_mock_provider("Sorry, I cannot help with that.")
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="Failed to parse"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_missing_required_field_raises_key_error(self):
        """LLM returning JSON without required fields raises KeyError."""
        from backend.skills.review_service import ReviewService

        incomplete = json.dumps({"name": "x"})  # missing description, etc.
        provider = _make_mock_provider(incomplete)
        service = ReviewService(provider)

        with pytest.raises(KeyError):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_llm_provider_exception_propagates(self):
        """If the LLM provider raises, the exception propagates to caller."""
        from backend.skills.review_service import ReviewService

        provider = Mock()
        provider.complete = AsyncMock(side_effect=RuntimeError("API down"))
        service = ReviewService(provider)

        with pytest.raises(RuntimeError, match="API down"):
            await service.generate_draft(trigger_type="t", context={})


# ---------------------------------------------------------------------------
# Tests: SkillDraft dataclass
# ---------------------------------------------------------------------------


class TestSkillDraftDataclass:
    """Verify SkillDraft dataclass structure."""

    def test_skill_draft_has_required_fields(self):
        """SkillDraft has all fields specified in the brief."""
        from backend.skills.review_service import SkillDraft

        draft = SkillDraft(
            id="abc",
            name="n",
            description="d",
            when_to_use="w",
            content="c",
            trigger_type="t",
            source_session_id="s",
            source_context={},
        )
        assert draft.status == "pending"
        assert draft.created_at == 0

    def test_skill_draft_default_status(self):
        """Default status is 'pending'."""
        from backend.skills.review_service import SkillDraft

        draft = SkillDraft(
            id="x",
            name="n",
            description="d",
            when_to_use="w",
            content="c",
            trigger_type="t",
            source_session_id="s",
            source_context={},
        )
        assert draft.status == "pending"
