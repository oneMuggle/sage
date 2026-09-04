"""Tests for ReviewService with LLM-driven skill draft generation."""

import json
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

    def test_default_review_service_uses_provider_client_contract(self, monkeypatch):
        """The production default must expose ProviderClient.complete()."""
        from backend.adapters.out.llm.openai import OpenAIProvider
        from backend.data.settings_repo import SettingsRepository
        from backend.ports.llm import ProviderClient
        from backend.skills import review_service

        monkeypatch.setattr(
            SettingsRepository,
            "get_json",
            lambda self, key: {
                "endpoints": [
                    {
                        "id": "e1",
                        "baseUrl": "https://api.example.test/v1",
                        "apiKey": "test-key",
                    }
                ],
                "modelSelections": {"chatModel": {"endpointId": "e1", "modelId": "review-model"}},
            },
        )
        review_service.reset_review_service()
        try:
            service = review_service.get_review_service()
            assert isinstance(service.llm_provider, ProviderClient)
            assert isinstance(service.llm_provider, OpenAIProvider)
        finally:
            review_service.reset_review_service()

    @pytest.mark.asyncio()
    async def test_default_provider_receives_selected_model_on_complete(self, monkeypatch):
        """The selected model is passed to the provider's complete contract."""
        from backend.data.settings_repo import SettingsRepository
        from backend.skills import review_service

        monkeypatch.setattr(
            SettingsRepository,
            "get_json",
            lambda self, key: {
                "endpoints": [
                    {
                        "id": "e1",
                        "protocol": "openai-compatible",
                        "baseUrl": "https://api.example.test/v1",
                        "apiKey": "test-key",
                    }
                ],
                "modelSelections": {
                    "chatModel": {"endpointId": "e1", "modelId": "configured-review-model"}
                },
            },
        )
        review_service.reset_review_service()
        try:
            service = review_service.get_review_service()
            service.llm_provider.complete = AsyncMock(
                return_value=_make_mock_turn(VALID_LLM_OUTPUT)
            )
            await service.generate_draft("complex_turn", {})
            assert service.llm_provider.complete.call_args.kwargs["model"] == "configured-review-model"
        finally:
            review_service.reset_review_service()

    def test_default_review_service_does_not_create_unconfigured_external_provider(self, monkeypatch):
        """Missing settings must not silently target api.openai.com."""
        from backend.data.settings_repo import SettingsRepository
        from backend.skills import review_service

        monkeypatch.setattr(SettingsRepository, "get_json", lambda self, key: {})
        review_service.reset_review_service()
        try:
            service = review_service.get_review_service()
            assert type(service.llm_provider).__name__ == "_UnavailableReviewProvider"
        finally:
            review_service.reset_review_service()

    def test_ollama_provider_allows_empty_api_key(self):
        """Ollama is local and must remain usable without an API key."""
        from backend.adapters.out.llm.ollama import OllamaProvider

        provider = OllamaProvider(api_key="")
        assert provider._api_key == ""  # noqa: SLF001

    @pytest.mark.asyncio()
    async def test_generate_draft_uses_selected_chat_model(self, monkeypatch):
        """Background review follows the persisted model selection."""
        from backend.data.settings_repo import SettingsRepository
        from backend.skills.review_service import ReviewService

        monkeypatch.setattr(
            SettingsRepository,
            "get_json",
            lambda self, key: {
                "modelSelections": {"chatModel": {"modelId": "configured-review-model"}}
            },
        )
        provider = _make_mock_provider(VALID_LLM_OUTPUT)
        await ReviewService(provider).generate_draft("complex_turn", {})

        assert provider.complete.call_args.kwargs["model"] == "configured-review-model"

    @pytest.mark.asyncio()
    async def test_generate_draft_keeps_default_model_without_selection(self, monkeypatch):
        """Missing model selection retains the backwards-compatible fallback."""
        from backend.data.settings_repo import SettingsRepository
        from backend.skills.review_service import ReviewService

        monkeypatch.setattr(SettingsRepository, "get_json", lambda self, key: {})
        provider = _make_mock_provider(VALID_LLM_OUTPUT)
        await ReviewService(provider).generate_draft("complex_turn", {})

        assert provider.complete.call_args.kwargs["model"] == "sonnet"

    @pytest.mark.asyncio()
    async def test_generate_draft_settings_failure_keeps_default_model(self, monkeypatch):
        """Settings I/O failures do not prevent draft generation."""
        from backend.data.settings_repo import SettingsRepository
        from backend.skills.review_service import ReviewService

        def fail(self, key):
            raise RuntimeError("settings unavailable")

        monkeypatch.setattr(SettingsRepository, "get_json", fail)
        provider = _make_mock_provider(VALID_LLM_OUTPUT)
        await ReviewService(provider).generate_draft("complex_turn", {})

        assert provider.complete.call_args.kwargs["model"] == "sonnet"

    @pytest.mark.asyncio()
    async def test_injected_provider_uses_stable_model_snapshot(self, monkeypatch):
        """注入 provider 后，设置变化不能让 endpoint/provider 与 model 拆配。"""
        from backend.data.settings_repo import SettingsRepository
        from backend.skills.review_service import ReviewService

        monkeypatch.setattr(
            SettingsRepository,
            "get_json",
            lambda self, key: {
                "modelSelections": {"chatModel": {"modelId": "model-at-construction"}}
            },
        )
        provider = _make_mock_provider(VALID_LLM_OUTPUT)
        service = ReviewService(provider)
        monkeypatch.setattr(
            SettingsRepository,
            "get_json",
            lambda self, key: {
                "modelSelections": {"chatModel": {"modelId": "different-model"}}
            },
        )

        await service.generate_draft("complex_turn", {})

        assert provider.complete.call_args.kwargs["model"] == "model-at-construction"

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
    async def test_none_text_raises_value_error(self):
        """LLM returning an AssistantTurn with text=None raises ValueError."""
        from backend.skills.review_service import ReviewService

        provider = Mock()
        provider.complete = AsyncMock(return_value=_make_mock_turn(None))
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="empty or None text"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_empty_string_text_raises_value_error(self):
        """LLM returning an AssistantTurn with text='' raises ValueError."""
        from backend.skills.review_service import ReviewService

        provider = Mock()
        provider.complete = AsyncMock(return_value=_make_mock_turn(""))
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="empty or None text"):
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


# ---------------------------------------------------------------------------
# Tests: schema validation (PR-1 UX closure)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """PR-1: LLM output must satisfy the enhanced schema constraints."""

    @pytest.mark.asyncio()
    async def test_name_regex_rejects_uppercase(self):
        """Skill name must be kebab-case (lowercase + digits + hyphens)."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "Test-Skill",  # uppercase T, S
                "description": "d",
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="kebab-case"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_name_regex_rejects_too_short(self):
        """Skill name must be ≥ 3 chars."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "ab",  # too short
                "description": "d",
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="3..40"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    @pytest.mark.parametrize(
        "bad_name",
        [
            "test_skill",
            "test skill",
            "test/skill",
            "test--skill",
            "-test-skill",
            "test-skill-",
        ],
    )
    async def test_name_regex_rejects_invalid_kebab_case(self, bad_name):
        """Skill names must use lowercase kebab-case without malformed hyphens."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": bad_name,
                "description": "d",
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="kebab-case"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_name_regex_rejects_too_long(self):
        """Skill name must be no longer than 40 chars."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "a" * 41,
                "description": "d",
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="3..40"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("name", ["abc", "a" * 40])
    async def test_name_regex_accepts_length_boundaries(self, name):
        """Three and 40 character names are valid length boundaries."""
        from backend.skills.review_service import ReviewService

        good = json.dumps(
            {
                "name": name,
                "description": "d",
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(good)
        service = ReviewService(provider)

        draft = await service.generate_draft(trigger_type="t", context={})
        assert draft.name == name

    @pytest.mark.asyncio()
    @pytest.mark.parametrize(
        "missing_section, content",
        [
            (
                "## 步骤",
                "# Skill\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            ),
            (
                "## 触发条件",
                "# Skill\n\n## 步骤\n\n1. x\n\n## 示例\n\ne",
            ),
            (
                "## 示例",
                "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt",
            ),
        ],
    )
    async def test_content_missing_each_required_section(self, missing_section, content):
        """content must contain each required section independently."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "test-skill",
                "description": "d",
                "when_to_use": "w" * 40,
                "content": content,
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match=missing_section):
            await service.generate_draft(trigger_type="t", context={})

        """Description must be ≤ 80 chars."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "test-skill",
                "description": "x" * 81,
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="≤ 80"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_when_to_use_too_short(self):
        """when_to_use must be ≥ 30 chars."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "test-skill",
                "description": "d",
                "when_to_use": "too short",  # 9 chars
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="≥ 30"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_valid_schema_passes(self):
        """A fully compliant draft should pass all schema checks."""
        from backend.skills.review_service import ReviewService, SkillDraft

        good = json.dumps(
            {
                "name": "git-branch-hopping",
                "description": "Switch between git branches while preserving uncommitted work",
                "when_to_use": "When the user repeatedly switches branches and needs to stash/unstash changes",
                "content": "# Git Branch Hopping\n\n## 步骤\n\n1. git stash\n2. git switch <branch>\n3. git stash pop\n\n## 触发条件\n\nUser switches branches with dirty working tree\n\n## 示例\n\nRun the three commands in order to move the changes safely.",
            }
        )
        provider = _make_mock_provider(good)
        service = ReviewService(provider)

        draft = await service.generate_draft(trigger_type="complex_turn", context={})
        assert isinstance(draft, SkillDraft)
        assert draft.name == "git-branch-hopping"
