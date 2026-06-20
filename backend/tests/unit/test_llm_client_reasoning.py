"""
Tests for LLMClient reasoning_content parsing.

Tests that LLMResponse correctly extracts reasoning_content from various
LLM provider response formats (Anthropic, OpenAI o1/o3, DeepSeek, etc.)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse


class TestLLMResponseReasoning:
    """Test LLMResponse dataclass reasoning_content field."""

    def test_reasoning_content_defaults_to_none(self):
        """LLMResponse.reasoning_content should default to None."""
        response = LLMResponse()
        assert response.reasoning_content is None

    def test_reasoning_content_can_be_set(self):
        """LLMResponse.reasoning_content should accept string values."""
        response = LLMResponse(reasoning_content="Let me think about this...")
        assert response.reasoning_content == "Let me think about this..."

    def test_reasoning_content_with_empty_string(self):
        """LLMResponse.reasoning_content should accept empty string."""
        response = LLMResponse(reasoning_content="")
        assert response.reasoning_content == ""


class TestLLMClientReasoningParsing:
    """Test LLMClient.chat() reasoning_content extraction from various providers."""

    @pytest.fixture
    def llm_client(self):
        """Create a test LLM client."""
        config = LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.test.com/v1",
            model="gpt-4",
        )
        return LLMClient(config)

    @pytest.mark.asyncio
    async def test_parse_reasoning_content_from_openai_format(self, llm_client):
        """Should extract reasoning_content from OpenAI-format response."""
        mock_response_data = {
            "id": "chatcmpl-test",
            "model": "gpt-4",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "The answer is 42.",
                        "reasoning_content": "Let me calculate: 6 * 7 = 42.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

        with patch.object(llm_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await llm_client.chat([{"role": "user", "content": "What is 6*7?"}])

            assert result.content == "The answer is 42."
            assert result.reasoning_content == "Let me calculate: 6 * 7 = 42."

    @pytest.mark.asyncio
    async def test_parse_reasoning_from_anthropic_format(self, llm_client):
        """Should extract reasoning from Anthropic-format response (using 'reasoning' key)."""
        mock_response_data = {
            "id": "chatcmpl-test",
            "model": "claude-3-opus",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Based on my analysis...",
                        "reasoning": "I need to consider multiple factors here...",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

        with patch.object(llm_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await llm_client.chat([{"role": "user", "content": "Analyze this."}])

            assert result.reasoning_content == "I need to consider multiple factors here..."

    @pytest.mark.asyncio
    async def test_reasoning_content_none_when_not_present(self, llm_client):
        """Should set reasoning_content to None when not in response."""
        mock_response_data = {
            "id": "chatcmpl-test",
            "model": "gpt-4",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello!",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

        with patch.object(llm_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await llm_client.chat([{"role": "user", "content": "Hi"}])

            assert result.content == "Hello!"
            assert result.reasoning_content is None

    @pytest.mark.asyncio
    async def test_reasoning_content_prefers_reasoning_content_over_reasoning(self, llm_client):
        """Should prefer 'reasoning_content' over 'reasoning' when both present."""
        mock_response_data = {
            "id": "chatcmpl-test",
            "model": "gpt-4",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Answer",
                        "reasoning_content": "Primary reasoning",
                        "reasoning": "Secondary reasoning",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }

        with patch.object(llm_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await llm_client.chat([{"role": "user", "content": "Test"}])

            assert result.reasoning_content == "Primary reasoning"

    @pytest.mark.asyncio
    async def test_reasoning_content_with_long_thinking(self, llm_client):
        """Should handle very long reasoning_content (multi-paragraph thinking)."""
        long_reasoning = """
Let me break down this complex problem step by step.

First, I need to understand the requirements:
1. The user wants to parse reasoning content
2. Multiple LLM providers have different formats
3. We need to handle all of them gracefully

Looking at the code structure, I see that...
[... many more paragraphs ...]

After careful analysis, I conclude that the best approach is...
"""
        mock_response_data = {
            "id": "chatcmpl-test",
            "model": "gpt-4",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Here's my solution.",
                        "reasoning_content": long_reasoning,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 500, "total_tokens": 600},
        }

        with patch.object(llm_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await llm_client.chat([{"role": "user", "content": "Complex question"}])

            assert result.reasoning_content == long_reasoning
            assert len(result.reasoning_content) > 100
