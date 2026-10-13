"""Tests for PromptComposer."""
from __future__ import annotations

import pytest

from backend.design.models import DesignSystem, DesignTemplate
from backend.design.prompt_composer import PromptComposer


@pytest.fixture()
def system():
    return DesignSystem(
        id="minimal",
        name="Minimal",
        category="general",
        description="A minimal design system",
        design_md="# Minimal Design System\n\nUse black and white only.",
        tokens_css=":root { --bg: #fff; --fg: #000; }",
        design_tokens={},
        tags=["minimal"],
    )


@pytest.fixture()
def template():
    return DesignTemplate(
        id="landing-page",
        name="Landing Page",
        kind="prototype",
        description="Product landing page",
        skill_md="# Landing Page\nCreate a hero section with CTA button.",
        example_html=None,
        assets={},
        design_system_required=True,
    )


class TestPromptComposer:
    def test_compose_includes_all_sections(self, system, template):
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief="Create a SaaS landing page for a developer tool",
        )
        assert "Minimal Design System" in prompt
        assert "Landing Page" in prompt
        assert "SaaS landing page" in prompt
        assert "<artifact" in prompt

    def test_compose_with_iteration_context(self, system, template):
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief="Original brief",
            iteration_context={
                "current_html": "<html><body>Old version</body></html>",
                "user_feedback": "Change the button to blue",
            },
        )
        assert "Old version" in prompt
        assert "Change the button to blue" in prompt

    def test_compose_without_iteration_has_no_iteration_section(
        self, system, template,
    ):
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief="Create a page",
            iteration_context=None,
        )
        assert "当前版本" not in prompt

    def test_compose_identifier_from_template(self, system, template):
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief="test",
        )
        assert "landing-page" in prompt
