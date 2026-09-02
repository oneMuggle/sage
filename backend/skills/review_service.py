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
from typing import Any, Dict, Optional

from backend.domain.message import Message

logger = logging.getLogger(__name__)

# Required keys in the LLM's JSON output
_REQUIRED_FIELDS = ("name", "description", "when_to_use", "content")
_DEFAULT_REVIEW_MODEL = "sonnet"


class _UnavailableReviewProvider:
    """Explicitly fail when no configured provider is available."""

    async def complete(self, **_: Any) -> Any:
        raise RuntimeError("Review provider is not configured")



@dataclass(frozen=True)
class _ReviewConfig:
    """不可拆分的 review provider/model 配置快照。"""

    provider: Any
    model: str


def _build_review_config() -> _ReviewConfig:
    """Resolve provider and model atomically from the same settings snapshot."""
    try:
        from backend.orchestration.llm_factory import resolve_provider_and_model_from_settings

        resolved = resolve_provider_and_model_from_settings()
        if resolved is not None:
            provider, model = resolved
            return _ReviewConfig(provider=provider, model=model)
    except Exception:  # noqa: BLE001 - review remains best-effort
        logger.warning("Unable to build configured review provider", exc_info=True)
    return _ReviewConfig(
        provider=_UnavailableReviewProvider(), model=_DEFAULT_REVIEW_MODEL
    )


def _resolve_injected_provider_model() -> str:
    """Resolve the injected provider's model once at service construction."""
    try:
        from backend.orchestration.llm_factory import resolve_model_from_settings

        model = resolve_model_from_settings()
        if model:
            return model
    except Exception:  # noqa: BLE001 - retain safe fallback for fake providers
        logger.warning("Unable to resolve review model", exc_info=True)
    return _DEFAULT_REVIEW_MODEL


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

    def __init__(self, llm_provider: Any, model: Optional[str] = None) -> None:
        self.llm_provider = llm_provider
        self._model = model or _resolve_injected_provider_model()
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
        with open(template_path, encoding="utf-8") as fh:
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
            model=self._model,
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


# ------------------------------------------------------------------ #
# Global singleton (same pattern as get_review_queue / get_skill_draft_store)
#
# PR-C §5.2: The bootstrap layer (backend.skills.review_bootstrap) needs a
# module-level factory so it can wire ``ReviewQueue`` against the
# process-wide LLMClient without forcing every caller to construct one
# explicitly. Tests can call ``get_review_service(provider=mock_provider)``
# to inject a fake — production paths let ``provider=None`` and pick up
# ``HttpxLLMAdapter`` lazily on the first real ``generate_draft`` call.
# ------------------------------------------------------------------ #
_review_service: Optional[ReviewService] = None


def get_review_service(
    llm_provider: Any = None,
) -> ReviewService:
    """Return the process-wide ReviewService.

    Args:
        llm_provider: An async ``complete()``-compatible object
            (``ProviderClient`` protocol). If ``None``, a settings-derived
            ``ProviderClient`` is constructed; without usable settings the
            service fails closed rather than sending data to a default endpoint.

    Subsequent calls ignore the ``llm_provider`` argument and return
    the cached singleton — this mirrors the behaviour of
    ``get_review_queue`` and ``get_skill_draft_store``.
    """
    global _review_service
    if _review_service is None:
        if llm_provider is None:
            config = _build_review_config()
            _review_service = ReviewService(config.provider, model=config.model)
        else:
            _review_service = ReviewService(llm_provider)
    return _review_service


def reset_review_service() -> None:
    """Reset the global ``ReviewService`` singleton (test only)."""
    global _review_service
    _review_service = None
