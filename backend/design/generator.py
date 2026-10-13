# backend/design/generator.py
"""Core design generation — compose prompt, call LLM, parse, bundle."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.design.artifact_parser import ArtifactParser, ParsedArtifact
from backend.design.errors import DesignGenerationError
from backend.design.models import DesignSystem, DesignTemplate
from backend.design.prompt_composer import PromptComposer
from backend.design.standalone_bundler import StandaloneBundler


@dataclass
class GenerationResult:
    """Result of a design generation."""

    parsed: ParsedArtifact
    bundled_html: str
    source_prompt: str


class DesignGenerator:
    """Generate HTML designs by composing prompts and calling LLM."""

    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    async def generate(
        self,
        system: DesignSystem,
        template: DesignTemplate,
        brief: str,
        iteration_context: Optional[dict] = None,
    ) -> GenerationResult:
        """Generate a design artifact.

        Raises DesignGenerationError if LLM output can not be parsed.
        """
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief=brief,
            iteration_context=iteration_context,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self._llm.chat(messages)
        raw_output = response.content

        if not raw_output:
            raise DesignGenerationError("LLM returned empty response")

        parsed = ArtifactParser.parse(raw_output)

        bundled = StandaloneBundler.bundle(
            html=parsed.html_content,
            css=system.tokens_css,
            assets=template.assets,
        )

        return GenerationResult(
            parsed=parsed,
            bundled_html=bundled,
            source_prompt=prompt,
        )
