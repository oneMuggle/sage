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
import re
import time
import uuid
from dataclasses import dataclass
from string import Template
from typing import Any, Dict, Optional, Tuple

from backend.domain.message import Message

logger = logging.getLogger(__name__)

# Required keys in the LLM's JSON output
_REQUIRED_FIELDS = ("name", "description", "when_to_use", "content")
_DEFAULT_REVIEW_MODEL = "sonnet"


class _UnavailableReviewProvider:
    """Explicitly fail when no configured provider is available."""

    async def complete(self, **_: Any) -> Any:
        raise RuntimeError("Review provider is not configured")


class _LLMClientReviewProvider:
    """ProviderClient 契约的 LLMClient 适配器 (L3)。

    ProviderClient 家族删除后, review 改走 LLMClient (settings 选定的
    openai-compatible 端点, L3 时已烘焙进 client 配置 —— complete() 的
    逐调用 model 参数被忽略)。messages 为 sage_core Message 列表, 转成
    role/content dict 交给 LLMClient.chat。
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def complete(self, **kwargs: Any) -> Any:
        from types import SimpleNamespace

        messages = kwargs.get("messages") or []
        payload = [
            {
                "role": (m.role.value if hasattr(m.role, "value") else m.role),
                "content": m.content,
            }
            for m in messages
        ]
        response = await self._client.chat(payload)
        return SimpleNamespace(text=response.content, model=getattr(response, "model", None))



@dataclass(frozen=True)
class _ReviewConfig:
    """不可拆分的 review provider/model 配置快照。"""

    provider: Any
    model: str


def _build_review_config() -> _ReviewConfig:
    """Resolve review LLM atomically from the same settings snapshot (L3)."""
    try:
        from backend.orchestration.llm_factory import (
            build_llm_client_from_settings,
            resolve_model_from_settings,
        )

        client = build_llm_client_from_settings()
        if client is not None:
            model = resolve_model_from_settings() or _DEFAULT_REVIEW_MODEL
            return _ReviewConfig(provider=_LLMClientReviewProvider(client), model=model)
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

    async def should_generate(
        self, context: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """LLM 初筛：这轮对话是否值得沉淀为可复用技能（Round 2）。

        对标 hermes background review fork 的判断力，但保留 Sage 的
        人工审批哲学 —— 初筛只决定"要不要起稿"，批准闸口不变。
        用于低阈值入队的边缘回合（工具调用 2~3 次），过滤噪音，
        避免"每次都起稿"的审批疲劳。

        Returns:
            (should_generate, reason) 二元组。
            LLM 不可用 / 输出不可解析 → (False, ...) —— 宁缺勿滥：
            初筛与起稿同样依赖 LLM，供应商故障时不可能起稿成功。

        Raises:
            Exception: LLM provider 异常照常上抛（worker 侧捕获计失败）。
        """
        prompt = (
            "以下是一轮 AI 助手对话的上下文（用户请求 + 工具调用序列）。"
            "请判断：这轮对话是否展示了一个**值得沉淀为可复用技能**的流程？\n"
            "判定标准（需同时满足）：\n"
            "1. 有可复用的步骤结构（不是一次性闲聊或简单问答）；\n"
            "2. 用户可能以相似方式再次提出（同类任务可复用）；\n"
            "3. 不是单次工具调用的平凡查询。\n\n"
            '只输出 JSON：{"save_skill": true/false, "reason": "一句话理由"}\n\n'
            "对话上下文:\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )
        turn = await self.llm_provider.complete(
            model=self._model,
            messages=[
                Message(role="system", content="你是一个技能策展人。请输出 JSON。"),
                Message(role="user", content=prompt),
            ],
        )
        if not turn.text:
            return False, "LLM 返回空响应"
        try:
            text = turn.text.strip()
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end <= start:
                return False, "初筛输出不可解析"
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return False, "初筛输出非 JSON"
        if isinstance(parsed, dict) and parsed.get("save_skill") is True:
            return True, str(parsed.get("reason", ""))
        return False, str(parsed.get("reason", "无充分证据")) if isinstance(parsed, dict) else "无充分证据"

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

        # Validate the enhanced draft schema before filesystem-specific checks.
        self._validate_skill_schema(parsed)

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
    def _validate_skill_schema(parsed: Dict[str, Any]) -> None:
        """Validate LLM output against the enhanced skill draft schema.

        Length checks use Python ``len()``, i.e. UTF-16 code units, not graphemes.
        Mirrors the counting convention used by ``backend/skills/skill_md/frontmatter.py``.

        Raises ``ValueError`` if the draft violates any constraint:
        - ``name`` must be a non-empty string matching the canonical kebab-case
          pattern (3..40 chars, lowercase+digits+hyphens, no leading/trailing or
          consecutive hyphens)
        - ``description`` must be a string of ≤ 80 chars
        - ``when_to_use`` must be a string of ≥ 30 chars
        - ``content`` must be a string containing ``## 步骤``, ``## 触发条件``, ``## 示例``

        Non-string values for any of the four fields raise ``ValueError`` so the
        failure mode matches the surrounding ``KeyError``/``ValueError`` contracts.

        Args:
            parsed: The parsed JSON dict from LLM output.

        Raises:
            ValueError: A schema constraint is violated.
        """
        name = parsed.get("name", "")
        if not isinstance(name, str):
            raise ValueError(
                f"name must be a string, got {type(name).__name__}"
            )
        if not name:
            raise ValueError("Skill name must not be empty")
        if not re.fullmatch(r"[a-z](?:[a-z0-9]|-[a-z0-9]){2,39}", name):
            raise ValueError(
                f"Skill name must be kebab-case (3..40 chars, lowercase+digits+hyphens): {name!r}"
            )

        description = parsed.get("description", "")
        if not isinstance(description, str):
            raise ValueError(
                f"description must be a string, got {type(description).__name__}"
            )
        if len(description) > 80:
            raise ValueError(
                f"Description must be ≤ 80 chars, got {len(description)}: {description!r}"
            )

        when_to_use = parsed.get("when_to_use", "")
        if not isinstance(when_to_use, str):
            raise ValueError(
                f"when_to_use must be a string, got {type(when_to_use).__name__}"
            )
        if len(when_to_use) < 30:
            raise ValueError(
                f"when_to_use must be ≥ 30 chars, got {len(when_to_use)}: {when_to_use!r}"
            )

        content = parsed.get("content", "")
        if not isinstance(content, str):
            raise ValueError(
                f"content must be a string, got {type(content).__name__}"
            )
        for section in ("## 步骤", "## 触发条件", "## 示例"):
            if section not in content:
                raise ValueError(
                    f"content must contain '{section}' section, got: {content[:100]!r}..."
                )

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
