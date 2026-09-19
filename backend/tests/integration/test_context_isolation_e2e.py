"""Task 13: Integration test — three layers of context isolation compose.

End-to-end exercise of:
1. Explicit topic_separator (advance_segment) + segment-aware history slicing
2. Turn limit (apply_turn_limit) reducing history to most-recent N user turns
3. Topic detection (detect_topic_shift) quick-signal triggering a separator

All three layers come from prior tasks (1, 2, 3, 9). This test verifies they
work together correctly via real DB state and real function calls.

Uses the project's autouse `setup_test_db` fixture (provides fresh in-memory DB
+ singleton resets) and the `ensure_session` helper (satisfies FK constraint
before inserting child rows into messages).
"""


import pytest

from backend.chat.history_context import apply_turn_limit, db_rows_to_history
from backend.chat.topic_detection import detect_topic_shift
from backend.data import session_repo
from backend.data.session_repo import Message, MessageRepository
from backend.data.settings_repo import SettingsRepository
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.integration


def test_explicit_separator_then_turn_limit(setup_test_db, monkeypatch):
    """Layer 1 (segment) + Layer 2 (turn limit) compose correctly.

    Setup: 5 turns in segment 0, advance to segment 1, then 10 turns.
    Expected: get_active_segment returns segment 1 only; apply_turn_limit
    keeps the most-recent 2 user turns from segment 1.

    Note: ``advance_segment`` uses ``time.time() * 1000`` for the separator's
    created_at; we monkeypatch it so the separator lands *between* the old
    messages (timestamp 1000..1014) and new messages (timestamp 2000..2019),
    matching the spec's expectation that the separator marks the boundary.
    """
    ensure_session(setup_test_db, "s1")

    # Pin time.time() so the separator's created_at = 1500 (between old & new)
    monkeypatch.setattr(session_repo.time, "time", lambda: 1.5)

    repo = MessageRepository()
    SettingsRepository().set("context_turn_limit", "2")

    # Segment 0 — 5 user/assistant turns
    for i in range(5):
        repo.insert("s1", "user", f"old-{i}", 1000 + i)
        repo.insert("s1", "assistant", f"old-reply-{i}", 1000 + i)

    # Layer 1: explicit topic separator (timestamp 1500)
    new_seg = repo.advance_segment("s1")
    assert new_seg == 1

    # Segment 1 — 10 user/assistant turns (timestamp 2000..2019)
    for i in range(10):
        repo.insert("s1", "user", f"new-{i}", 2000 + i)
        repo.insert("s1", "assistant", f"new-reply-{i}", 2000 + i)

    active = repo.get_active_segment("s1")
    history = db_rows_to_history(active)
    kept, omitted = apply_turn_limit(history, turn_limit=2)

    user_contents = [m["content"] for m in kept if m["role"] == "user"]
    assert user_contents == ["new-8", "new-9"], f"expected last 2 user turns, got {user_contents}"
    # All kept messages come from segment 1
    assert all(not c.startswith("old-") for c in [m["content"] for m in kept]), (
        "segment 0 messages leaked into active segment"
    )


def test_topic_detection_triggers_separator(setup_test_db, monkeypatch):
    """Layer 3 (topic detection) + Layer 1 (segment) compose correctly.

    Setup: assistant message about bug fix; user types "By the way, completely
    different" which matches the quick-signal regex. After detection triggers
    advance_segment, get_active_segment should not include the bug-fix message.

    Time is pinned so the separator (timestamp 100) lands *after* the
    "Bug fix explanation" (timestamp 1) but *before* the "Weather question"
    (timestamp 200), so the active segment contains only the latter.
    """
    ensure_session(setup_test_db, "s1")

    monkeypatch.setattr(session_repo.time, "time", lambda: 0.1)

    repo = MessageRepository()
    repo.insert("s1", "assistant", "Bug fix explanation", 1)

    # Layer 3: detect quick-signal topic shift
    is_new, reason = detect_topic_shift(
        "By the way, completely different", ["Bug fix explanation"]
    )
    assert is_new is True
    assert reason == "quick_signal"

    # Layer 1: trigger segment advance based on detection
    if is_new:
        repo.advance_segment("s1")
    repo.insert("s1", "user", "Weather question", 200)

    active = repo.get_active_segment("s1")
    # Bug fix explanation is in segment 0; active segment (1) should not contain it
    assert all(
        getattr(m, "content", "") != "Bug fix explanation" for m in active
    ), "old segment leaked into active after topic shift"
    # Sanity: the new user message IS in the active segment
    assert any(getattr(m, "content", "") == "Weather question" for m in active), (
        "new user message not found in active segment"
    )


def test_save_persists_active_segment_id(setup_test_db):
    """Regression (2026-09-18): save() must persist segment_id aligned with
    get_active_segment_id() so MemoryManager.get_context(segment_id=N) can
    filter working memory correctly after advance_segment().

    Bug: earlier save() INSERT omitted segment_id, so post-advance user/assistant
    rows stayed at default 0 while MAX(segment_id)=1, causing segment-scoped
    memory queries to miss freshly written messages.
    """
    ensure_session(setup_test_db, "s1")
    repo = MessageRepository()

    # Segment 0: one user message via save()
    repo.save(
        Message(
            id="m0",
            session_id="s1",
            role="user",
            content="initial topic",
            created_at=1,
        )
    )
    assert repo.get_active_segment_id("s1") == 0
    assert repo.save.__self__  # sanity: repo usable

    # Advance → segment 1
    new_seg = repo.advance_segment("s1")
    assert new_seg == 1

    # Post-advance user message via save()
    repo.save(
        Message(
            id="m1",
            session_id="s1",
            role="user",
            content="new topic question",
            created_at=200,
        )
    )
    # And an assistant reply via save()
    repo.save(
        Message(
            id="m2",
            session_id="s1",
            role="assistant",
            content="new topic answer",
            created_at=201,
        )
    )

    # Critical assertion: get_active_segment_id returns 1, and the messages
    # saved AFTER advance_segment must persist segment_id=1 (not 0)
    assert repo.get_active_segment_id("s1") == 1

    conn = repo.db.get_connection()
    rows = conn.execute(
        "SELECT id, segment_id, subtype FROM messages WHERE session_id = ? ORDER BY created_at",
        ("s1",),
    ).fetchall()
    by_id = {r["id"]: dict(r) for r in rows}

    # Initial segment 0 message stays at segment 0
    assert by_id["m0"]["segment_id"] == 0
    assert by_id["m0"]["subtype"] is None
    # Post-advance messages land on segment 1 (not stuck at 0)
    assert by_id["m1"]["segment_id"] == 1, (
        "save() failed to persist active segment_id — memory filter will miss this row"
    )
    assert by_id["m2"]["segment_id"] == 1
    # advance_segment separator is fully marked in a single INSERT
    sep_row = next(r for r in rows if r["id"] != "m0" and r["id"] not in ("m1", "m2"))
    assert sep_row["segment_id"] == 1
    assert sep_row["subtype"] == "topic_separator"
