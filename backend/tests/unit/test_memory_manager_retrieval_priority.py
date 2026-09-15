"""Unit tests for 3-tier retrieval priority (批次三 step 5).

Spec §4.3 step 5:

    检索优先级定义为：working context → 当前 session summary → episodic/semantic
    长期记忆。不同 session 不得互相注入摘要。

Contract under test (lives on ``MemoryManager.get_context``):

* working context is always pulled first, by bound ``session_id``
* the *current* session's READY summary (if any) is injected next
* FAILED / PENDING summary rows are NEVER injected (silent lies)
* other sessions' summaries are NEVER injected (cross-session leak guard)
* episodic / semantic long-term memory comes after, scoped to session_id
* if ``session_id`` is None or no READY summary exists for the bound
  session, the summary block is omitted (no fallback to "summary of all
  sessions")
"""

from __future__ import annotations

from typing import List

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.summary import (
    FAILED,
    READY,
    SessionSummaryStore,
)
from backend.memory.working import WorkingMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


@pytest.fixture()
def manager(tmp_db_path: str) -> MemoryManager:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    ensure_session(db, "s1")
    ensure_session(db, "s2")
    return MemoryManager(
        working=WorkingMemory(max_size=10, max_tokens=2000),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
        summary_store=SessionSummaryStore(db),
    )


def _section_headers(text: str) -> List[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("【") and line.strip().endswith("】")
    ]


# ──────────────────────────────────────────────────────────────────────
# Public surface: MemoryManager wires a summary_store
# ──────────────────────────────────────────────────────────────────────


def test_manager_exposes_summary_store(manager: MemoryManager) -> None:
    assert isinstance(manager.summary_store, SessionSummaryStore)


# ──────────────────────────────────────────────────────────────────────
# 3-tier ordering: working → summary → episodic/semantic
# ──────────────────────────────────────────────────────────────────────


def test_get_context_uses_three_tier_ordering(manager: MemoryManager) -> None:
    """Spec step 5: working context comes first, then current session's
    summary, then episodic/semantic. The order must NOT be reshuffled
    or the LLM will see long-term facts before fresh context.
    """
    manager.summary_store.create(
        session_id="s1",
        content="User previously asked about office round-trip.",
        status=READY,
    )
    manager.add_to_working("user", "now asking about docx", session_id="s1")
    # Avoid the episodic/semantic section having no signal — we just
    # care about *order*, not whether the section appears.
    manager.episodic.save(
        content="old episodic fact",
        session_id="s1",
    )

    ctx = manager.get_context(limit=10, session_id="s1")
    headers = _section_headers(ctx)

    # Section order matches the spec.
    assert "【当前对话】" in headers
    assert "【会话摘要】" in headers
    assert headers.index("【会话摘要】") > headers.index("【当前对话】")
    # The episodic header appears AFTER the summary section.
    assert "【相关经历】" in headers
    assert headers.index("【相关经历】") > headers.index("【会话摘要】")


def test_get_context_summary_block_only_for_current_session(
    manager: MemoryManager,
) -> None:
    """Only the bound session's READY summary is injected. s2's summary
    must NEVER appear in s1's context (cross-session leak guard).
    """
    manager.summary_store.create(
        session_id="s1",
        content="s1 summary: office docx tooling",
        status=READY,
    )
    manager.summary_store.create(
        session_id="s2",
        content="s2 summary: xlsx chart macros",
        status=READY,
    )

    s1_ctx = manager.get_context(limit=10, session_id="s1")
    assert "s1 summary: office docx tooling" in s1_ctx
    assert "s2 summary: xlsx chart macros" not in s1_ctx

    s2_ctx = manager.get_context(limit=10, session_id="s2")
    assert "s2 summary: xlsx chart macros" in s2_ctx
    assert "s1 summary: office docx tooling" not in s2_ctx


def test_get_context_skips_failed_summaries(manager: MemoryManager) -> None:
    """FAILED rows MUST NOT be injected. A failed summary is a
    diagnostic — silently promoting it to context would be a
    spec-§4.3-step-4 violation.
    """
    manager.summary_store.create(
        session_id="s1",
        content="",
        status=FAILED,
        error_message="LLM timeout",
    )

    ctx = manager.get_context(limit=10, session_id="s1")
    assert "【会话摘要】" not in _section_headers(ctx)
    # Diagnostic text must not leak into context either.
    assert "LLM timeout" not in ctx


def test_get_context_skips_summary_when_no_session_id(
    manager: MemoryManager,
) -> None:
    """No bound session → no summary section. We don't inject "summary
    of all sessions" because that would silently bleed session context
    into unrelated calls.
    """
    manager.summary_store.create(
        session_id="s1",
        content="would leak if injected without session filter",
        status=READY,
    )

    ctx = manager.get_context(limit=10, session_id=None)
    assert "【会话摘要】" not in _section_headers(ctx)
    assert "would leak if injected without session filter" not in ctx


def test_get_context_skips_summary_when_session_has_none(
    manager: MemoryManager,
) -> None:
    """If the bound session has no READY summary, skip the block
    cleanly — don't synthesize one from working context (that's the
    generation hook's job, not retrieval).
    """
    # s1 has no summary row at all.
    ctx = manager.get_context(limit=10, session_id="s1")
    assert "【会话摘要】" not in _section_headers(ctx)


def test_get_context_uses_latest_ready_summary(manager: MemoryManager) -> None:
    """get_latest_ready semantics must flow through get_context: when
    multiple READY summaries exist for the same session, only the most
    recent one is injected (the others are stale).
    """
    import time as _time

    manager.summary_store.create(
        session_id="s1",
        content="older summary",
        status=READY,
    )
    _time.sleep(0.01)
    manager.summary_store.create(
        session_id="s1",
        content="newer summary",
        status=READY,
    )

    ctx = manager.get_context(limit=10, session_id="s1")
    assert "newer summary" in ctx
    assert "older summary" not in ctx


# ──────────────────────────────────────────────────────────────────────
# The summary injection does NOT collide with working-context isolation
# ──────────────────────────────────────────────────────────────────────


def test_get_context_working_isolation_holds_with_summary(
    manager: MemoryManager,
) -> None:
    """Working context must remain session-scoped (existing behavior) —
    adding a summary block must not accidentally widen the working
    filter or cause s2's messages to bleed into s1's context.
    """
    manager.summary_store.create(
        session_id="s1",
        content="s1 summary",
        status=READY,
    )
    manager.add_to_working("user", "s2 secret message", session_id="s2")
    manager.add_to_working("user", "s1 public message", session_id="s1")

    ctx = manager.get_context(limit=10, session_id="s1")
    assert "s1 public message" in ctx
    assert "s2 secret message" not in ctx
