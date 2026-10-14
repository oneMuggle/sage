# backend/tests/unit/test_design_generator.py
"""Tests for DesignGenerator."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.design.errors import DesignGenerationError
from backend.design.generator import DesignGenerator
from backend.design.models import DesignSystem, DesignTemplate
from backend.design.prompt_composer import PromptComposer


@pytest.fixture()
def system():
    return DesignSystem(
        id="minimal",
        name="Minimal",
        category="general",
        description="Minimal",
        design_md="# Minimal",
        tokens_css=":root { --bg: #fff; }",
        design_tokens={},
        tags=[],
    )


@pytest.fixture()
def template():
    return DesignTemplate(
        id="landing-page",
        name="Landing Page",
        kind="prototype",
        description="Landing page",
        skill_md="# Landing Page",
        example_html=None,
        assets={},
        design_system_required=True,
    )


@pytest.fixture()
def mock_llm():
    llm = MagicMock()
    llm.chat = AsyncMock()
    return llm


class TestDesignGenerator:
    @pytest.mark.asyncio()
    async def test_generate_success(self, system, template, mock_llm):
        mock_llm.chat.return_value = MagicMock(
            content=(
                '<artifact identifier="landing-page" type="text/html"'
                ' title="Landing Page">\n'
                "<!DOCTYPE html><html><body><h1>Test</h1></body></html>"
                "\n</artifact>"
            )
        )

        generator = DesignGenerator(llm_client=mock_llm)
        result = await generator.generate(
            system,
            template,
            "Create a landing page",
        )

        assert "Test" in result.bundled_html
        assert ":root { --bg: #fff; }" in result.bundled_html
        assert result.parsed.identifier == "landing-page"

    @pytest.mark.asyncio()
    async def test_generate_no_artifact_raises(self, system, template, mock_llm):
        mock_llm.chat.return_value = MagicMock(
            content="Just text, no artifact.",
        )

        generator = DesignGenerator(llm_client=mock_llm)
        with pytest.raises(DesignGenerationError):
            await generator.generate(system, template, "test")

    @pytest.mark.asyncio()
    async def test_generate_sends_domain_messages(
        self, system, template, mock_llm,
    ):
        """The LLM adapter expects domain.Message, not plain dicts — a dict
        would raise AttributeError on the adapter's attribute access.
        """
        from sage_core import Message, Role

        mock_llm.chat.return_value = MagicMock(
            content=(
                '<artifact identifier="landing-page" type="text/html"'
                ' title="Landing Page">\n'
                "<!DOCTYPE html><html><body><h1>Test</h1></body></html>"
                "\n</artifact>"
            )
        )
        generator = DesignGenerator(llm_client=mock_llm)
        await generator.generate(system, template, "Create a landing page")
        messages = mock_llm.chat.call_args.args[0]
        assert len(messages) == 1
        assert isinstance(messages[0], Message)
        assert messages[0].role is Role.USER
        assert messages[0].content == PromptComposer.compose(
            design_system=system,
            template=template,
            brief="Create a landing page",
        )
