"""ReviewService — LLM-driven skill draft generation.

Consumes a trigger type and conversation context, calls an LLM provider
to analyze the context, and produces a SkillDraft dataclass that can
later be promoted into a full SKILL.md.

The LLM provider is expected to expose an async ``complete()`` method
matching ``ProviderClient`` (returns an object with a ``.text`` attribute).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from string import Template
from typing import Any, Dict

from backend.domain.message import Message

logger = logging.getLogger(__name__)

# Required keys in the LLM's JSON output
_REQUIRED_FIELDS = ("name", "description", "when_to_use", "content")


@dataclass
class SkillDraft:
    """A skill draft produced by the LLM review process.

    ``status`` starts at ``"pending"``; downstream components (Task 6)
    transition it through ``"approved"`` / ``"rejected"``.
    """

    id: str
    name: str
    description: str
    when_to_use: str
    content: str
    trigger_type: str
    source_session_id: str
    source_context: Dict[str, Any]
    status: str = "pending"
    created_at: int = 0


class ReviewService:
    """Generate skill drafts from conversation context using an LLM.

    Args:
        llm_provider: An object with an async ``complete()`` method
            (``ProviderClient``-compatible). The method must accept
            ``model`` and ``messages`` keyword arguments and return an
            object with a ``.text`` attribute.
    """

    def __init__(self, llm_provider: Any) -> None:
        self.llm_provider = llm_provider
        self._prompt_template = self._load_prompt_template()

    # ------------------------------------------------------------------ #
    # Prompt template
    # ------------------------------------------------------------------ #

    def _load_prompt_template(self) -> Template:
        """Load the prompt template from the prompts/ directory.

        Uses Python's stdlib ``string.Template`` (``$variable`` syntax).
        Jinja2 is intentionally *not* used — the substitution required
        here is trivial, so adding a dependency would violate YAGNI.
        """
        from pathlib import Path

        template_path = Path(__file__).parent / "prompts" / "review.txt"
        with open(template_path, "r", encoding="utf-8") as fh:
            return Template(fh.read())

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def generate_draft(
        self, trigger_type: str, context: Dict[str, Any]
    ) -> SkillDraft:
        """Generate a skill draft using the LLM provider.

        Args:
            trigger_type: The type of review trigger that fired
                (e.g. ``"complex_turn"``, ``"repeated_pattern"``).
            context: Conversation context dict — must include any data
                the prompt template needs (``session_id``, ``tool_calls``,
                etc.).

        Returns:
            A populated ``SkillDraft`` with ``status="pending"``.

        Raises:
            ValueError: The LLM output could not be parsed as JSON.
            KeyError: The parsed JSON is missing a required field.
            Exception: Any exception raised by the LLM provider
                propagates unchanged.
        """
        prompt = self._prompt_template.substitute(
            trigger_type=trigger_type,
            conversation_context=json.dumps(
                context, ensure_ascii=False, indent=2
            ),
        )

        messages = [
            Message(
                role="system",
                content="你是一个技能策展人。请输出 JSON 格式的技能草稿。",
            ),
            Message(role="user", content=prompt),
        ]

        turn = await self.llm_provider.complete(
            model="sonnet",
            messages=messages,
        )

        if not turn.text:
            raise ValueError(
                "LLM provider returned an AssistantTurn with empty or None text"
            )

        parsed = self._parse_llm_output(turn.text)

        # Validate required fields — raises KeyError if missing
        for key in _REQUIRED_FIELDS:
            _ = parsed[key]

        # Validate skill name for safe filesystem storage (I-1 fix).
        # Catches LLM hallucinations like "../etc/cron.d/backdoor" or
        # "foo/bar" before the draft enters the store, so the user can
        # never reach approve_skill_draft with an un-writable name.
        self._validate_skill_name(parsed["name"])

        return SkillDraft(
            id=str(uuid.uuid4()),
            name=parsed["name"],
            description=parsed["description"],
            when_to_use=parsed["when_to_use"],
            content=parsed["content"],
            trigger_type=trigger_type,
            source_session_id=context.get("session_id", ""),
            source_context=context,
            status="pending",
            created_at=int(time.time() * 1000),
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_skill_name(name: str) -> None:
        """Validate a skill name for safe filesystem storage.

        Raises ``ValueError`` if the name is empty, contains path
        traversal sequences, or includes directory separators. This
        prevents LLM-generated drafts with invalid names (e.g.
        ``"../etc/passwd"``, ``"foo/bar"``, ``""``) from being stored
        and later failing approval with opaque OS errors.

        Args:
            name: The skill name to validate.

        Raises:
            ValueError: The name is invalid for filesystem storage.
        """
        if not name or not name.strip():
            raise ValueError("Skill name must not be empty")
        if ".." in name:
            raise ValueError(
                f"Skill name must not contain path traversal sequences: {name!r}"
            )
        if "/" in name or "\\" in name:
            raise ValueError(
                f"Skill name must not contain directory separators: {name!r}"
            )

    def _parse_llm_output(self, output: str) -> Dict[str, Any]:
        """Extract and parse JSON from LLM output.

        Handles bare JSON, `````json`` fenced blocks, and plain `````
        fenced blocks. Raises ``ValueError`` on parse failure.
        """
        text = output.strip()

        # Try ```json ... ``` first, then ``` ... ```
        for fence in ("```json", "```"):
            start_idx = text.find(fence)
            if start_idx != -1:
                content_start = start_idx + len(fence)
                end_idx = text.find("```", content_start)
                if end_idx != -1:
                    text = text[content_start:end_idx].strip()
                    break

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Failed to parse LLM output as JSON: {exc}"
            ) from exc
