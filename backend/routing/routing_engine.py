"""Smart model routing engine.

Resolves a task type to a model tier, filters the available models by
context length and required capabilities, and selects the best match.

Tier fallback chain: preferred tier -> balanced -> fast -> powerful ->
first available model.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from pydantic import BaseModel

from backend.model_catalog.schemas import EffectiveModel

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids importing the DB layer
    from backend.model_catalog.repository import CatalogRepository


# ---------------------------------------------------------------------------
# Task-type -> tier mapping
# ---------------------------------------------------------------------------
# Canonical mapping from task-type labels (supplied by callers / UI) to the
# three routing tiers.  Unknown task types fall back to "balanced".

TASK_TYPE_TO_TIER: Dict[str, str] = {
    "simple_chat": "fast",
    "chat": "fast",
    "code_generation": "balanced",
    "code_review": "powerful",
    "analysis": "powerful",
    "writing": "balanced",
    "translation": "fast",
    "summarization": "balanced",
    "vision_task": "balanced",
}

# Default tier when the task type is not in the mapping.
_DEFAULT_TIER = "balanced"

# Fallback order used when the preferred tier has no matching model.
_TIER_FALLBACK = ("balanced", "fast", "powerful")

# Maximum number of alternative models returned in a RoutingResult.
_MAX_ALTERNATIVES = 3


# ---------------------------------------------------------------------------
# RoutingPreference
# ---------------------------------------------------------------------------

class RoutingPreference(BaseModel):
    """Optional user preferences applied on top of the automatic routing.

    Attributes:
        preferred_tier: Overrides the tier derived from the task type.
        locked_model: When set, this exact model is used and automatic
            selection is skipped entirely.
    """

    preferred_tier: Optional[str] = None
    locked_model: Optional[EffectiveModel] = None


# ---------------------------------------------------------------------------
# RoutingResult
# ---------------------------------------------------------------------------

class RoutingResult(BaseModel):
    """Outcome of a single routing decision.

    Attributes:
        selected_model: The chosen EffectiveModel.
        reason: Human-readable explanation of *why* this model was chosen.
        alternatives: Other candidate models (excluding the selected one),
            capped at ``_MAX_ALTERNATIVES``.
    """

    selected_model: EffectiveModel
    reason: str
    alternatives: List[EffectiveModel]


# ---------------------------------------------------------------------------
# RoutingEngine
# ---------------------------------------------------------------------------

class RoutingEngine:
    """Smart model routing engine.

    The engine reads the effective models from the model catalog and answers
    routing queries.  It holds no state of its own beyond the repository
    reference.

    Args:
        catalog_repository: The model catalog repository, used to enumerate
            the available (bound) models.
    """

    def __init__(self, catalog_repository: CatalogRepository) -> None:
        self.catalog = catalog_repository

    # -- public API ---------------------------------------------------------

    def route(
        self,
        task_type: str,
        context_length: int,
        required_capabilities: Optional[List[str]] = None,
        user_preference: Optional[RoutingPreference] = None,
        endpoint_id: Optional[str] = None,
    ) -> RoutingResult:
        """Select the best model for the given task requirements.

        Routing steps:
          1. Read the available models from the catalog.
          2. Filter by context length (``limits.native >= context_length``).
          3. Filter by required capabilities.
          4. Honour an explicitly locked model, if the user pinned one.
          5. Resolve the target tier from *task_type* (or the user's
             ``preferred_tier``) and select the first matching model.
          6. Build a ``RoutingResult`` with alternatives.

        Args:
            task_type: Logical task label (e.g. ``"code_generation"``).
            context_length: Minimum required context window in tokens.
            required_capabilities: Capabilities the model must support.
            user_preference: Optional user preferences.
            endpoint_id: When provided, restrict selection to models bound
                to this endpoint.  ``None`` (default) keeps whole-catalog
                behaviour, byte-identical to earlier versions.

        Returns:
            A ``RoutingResult`` with the selected model, a reason string, and
            up to three alternatives.

        Raises:
            ValueError: If no available model satisfies the requirements.
        """
        available_models = self._get_available_models(endpoint_id)

        # 1. Filter by context length
        filtered = [
            m for m in available_models
            if (m.limits.native or 0) >= context_length
        ]

        # 2. Filter by capabilities
        for capability in required_capabilities or []:
            filtered = [m for m in filtered if _supports_capability(m, capability)]

        if not filtered:
            raise ValueError(
                f"No models match requirements: "
                f"context={context_length}, "
                f"capabilities={list(required_capabilities or [])}"
            )

        # 3. An explicitly locked model short-circuits automatic selection.
        if user_preference and user_preference.locked_model:
            return RoutingResult(
                selected_model=user_preference.locked_model,
                reason="用户已锁定模型",
                alternatives=filtered[:_MAX_ALTERNATIVES],
            )

        # 4. Determine the target tier
        preferred_tier = TASK_TYPE_TO_TIER.get(task_type, _DEFAULT_TIER)
        if user_preference and user_preference.preferred_tier:
            preferred_tier = user_preference.preferred_tier

        # 5. Select the model
        selected = self._select_by_tier(filtered, preferred_tier)

        # 6. Build the result
        reason = f"已为 {task_type} 选择 {selected.tier} 模型"
        alternatives = [m for m in filtered if m != selected][:_MAX_ALTERNATIVES]

        return RoutingResult(
            selected_model=selected,
            reason=reason,
            alternatives=alternatives,
        )

    # -- internals ----------------------------------------------------------

    def _get_available_models(
        self, endpoint_id: Optional[str] = None
    ) -> List[EffectiveModel]:
        """Return the models currently reachable through the catalog.

        When *endpoint_id* is ``None`` the catalog is queried without
        arguments so that test fakes whose ``list_effective_models`` takes
        no parameters continue to work.
        """
        if endpoint_id is None:
            return self.catalog.list_effective_models()
        return self.catalog.list_effective_models(endpoint_id=endpoint_id)

    @staticmethod
    def _select_by_tier(
        models: List[EffectiveModel],
        preferred_tier: str,
    ) -> EffectiveModel:
        """Return the first model matching *preferred_tier*.

        When no model carries that tier the fallback chain (balanced -> fast
        -> powerful) is walked; if none of those tiers are present the first
        available model is returned.
        """
        search_order = [preferred_tier]
        search_order.extend(t for t in _TIER_FALLBACK if t != preferred_tier)

        for tier in search_order:
            for model in models:
                if model.tier == tier:
                    return model

        # Nothing matched any known tier — return the first available.
        return models[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _supports_capability(model: EffectiveModel, capability: str) -> bool:
    """Whether *model* supports *capability*.

    ``EffectiveModel.capabilities`` is a ``{capability: supported}`` mapping.
    When the mapping is absent (``None``) the model's capabilities are
    unknown, so the model is treated as permissive and is **not** dropped.
    When the mapping is present it is strict: the capability counts as
    supported only when its value is exactly ``True``.
    """
    capabilities = model.capabilities
    if capabilities is None:
        return True
    return capabilities.get(capability) is True
