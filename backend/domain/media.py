"""Rich media contract for tool outputs.

Tools that produce images / diagrams / audio / documents should not inline base64
payloads into the LLM-visible result. Instead they persist bytes via MediaStore
and return a :class:`RichMedia` reference wrapped by :func:`media_envelope`. The
envelope exposes a short human-readable ``text`` for the model plus a
``metadata`` block (``mediaRefs`` / ``richMedia``) for the UI renderer.

P1 of the self-hosted service framework (see docs/technical/172-*).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RichMedia:
    """A URL-only reference to a tool-produced media asset.

    Never carries raw bytes / base64 — ``api_url`` is the single source of
    truth for the payload. ``interactive`` hints that the renderer may offer
    zoom / pan / fullscreen (SVG diagrams being the canonical case).
    """

    id: str
    kind: str
    mime_type: str
    api_url: str
    format: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    interactive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "api_url": self.api_url,
            "format": self.format,
            "title": self.title,
            "source": self.source,
            "interactive": self.interactive,
        }


def media_envelope(
    text: str,
    media: List[RichMedia],
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a tool-result envelope.

    ``text`` is what the model sees; ``metadata.mediaRefs`` / ``richMedia``
    carry the same payload the UI renderer consumes. ``extra_metadata`` is
    merged verbatim for callers that need additional hints (e.g. legacy
    ``imageData`` fallback while the persist path is rolled out).
    """
    refs = [m.to_dict() for m in media]
    metadata: Dict[str, Any] = {"mediaRefs": refs, "richMedia": refs}
    if extra_metadata:
        metadata.update(extra_metadata)
    return {"text": text, "metadata": metadata}
