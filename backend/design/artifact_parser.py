"""Parse <artifact> blocks from LLM output."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.design.errors import DesignGenerationError


@dataclass(frozen=True)
class ParsedArtifact:
    """A parsed artifact block from LLM output."""

    identifier: str
    type: str
    title: str
    html_content: str


_ARTIFACT_RE = re.compile(
    r'<artifact\s+identifier="([^"]+)"\s+type="([^"]+)"'
    r'\s+title="([^"]+)">\s*(.*?)\s*</artifact>',
    re.DOTALL,
)


class ArtifactParser:
    """Extract <artifact> blocks from LLM output text."""

    @staticmethod
    def parse(text: str) -> ParsedArtifact:
        """Parse the first <artifact> block from text.

        Raises DesignGenerationError if no artifact block is found
        or if it is unclosed.
        """
        match = _ARTIFACT_RE.search(text)
        if match is None:
            if "<artifact" in text and "</artifact>" not in text:
                raise DesignGenerationError(
                    "Unclosed <artifact> tag in LLM output"
                )
            raise DesignGenerationError(
                "No <artifact> block found in LLM output"
            )

        return ParsedArtifact(
            identifier=match.group(1),
            type=match.group(2),
            title=match.group(3),
            html_content=match.group(4),
        )
