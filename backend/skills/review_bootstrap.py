"""PR-C §5.2: ReviewQueue 协作对象的启动期装配 (early-bind, fail-fast).

Background:
    ``ReviewQueue.review_service`` and ``.draft_store`` were declared as
    ``None`` on the singleton and **only test files** set them manually.
    In production hex/legacy paths, ``ReviewQueue.start()`` was never
    called either — meaning every ``complex_turn`` / ``low_success_rate``
    / ``explicit_learn`` event enqueued in main() produced a
    ``review_events`` row that the worker silently dropped with
    ``logger.error("ReviewService or SkillDraftStore not configured")``.

Fix:
    Inject both collaborators at ``lifespan`` startup, in the same style
    as ``init_scheduler_service`` / ``init_permission_gate`` /
    ``init_question_gate`` (see ``backend/main.py:182-232``).

Why early-bind, not lazy:
    - The three collaborators are all singletons (LLMClient, Database,
      SkillDraftStore). 0 startup cost.
    - Failure surfaces in lifespan log, not on first user action.
    - Matches the pattern of every other init_* singleton.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def bootstrap_review_collaborators(
    queue: Optional[Any] = None,
    review_service: Optional[Any] = None,
    draft_store: Optional[Any] = None,
) -> None:
    """Wire ``ReviewService`` and ``SkillDraftStore`` into the process-wide
    ``ReviewQueue`` singleton.

    Called once from ``backend/main.py:182-232`` lifespan block.
    All three parameters are injectable so unit tests can swap in mocks
    without booting the global LLMClient.

    Idempotency: re-calling with the SAME instances is a no-op. Re-calling
    with different instances replaces (and logs a warning) — the second
    case mostly happens during test-suite reload, not in production.
    """
    from backend.skills.draft_store import get_skill_draft_store
    from backend.skills.review_queue import get_review_queue
    from backend.skills.review_service import get_review_service

    if queue is None:
        queue = get_review_queue()
    if review_service is None:
        review_service = get_review_service()
    if draft_store is None:
        draft_store = get_skill_draft_store()

    queue.set_review_service(review_service)
    queue.set_draft_store(draft_store)

    logger.info(
        "ReviewQueue 协作对象已注入: review_service=%s draft_store=%s",
        type(review_service).__name__,
        type(draft_store).__name__,
    )
