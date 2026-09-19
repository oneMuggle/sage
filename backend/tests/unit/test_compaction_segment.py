# backend/tests/unit/test_compaction_segment.py
from backend.chat.compaction import should_compact


def test_should_compact_counts_active_messages(monkeypatch):
    """Verify should_compact returns True for a long active segment.

    Task 12 contract: compaction operates on whatever list the caller passes.
    The caller (chat_stream_create) must pass only get_active_segment(),
    not the full get_by_session(). These tests verify should_compact itself
    behaves correctly on long and short message lists; the caller-side
    restriction is verified by manual review of legacy_routes.py.
    """
    # Use a low explicit threshold to make the test deterministic across
    # environments (default threshold varies by history_token_budget).
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "100")
    msgs = [{"role": "user", "content": f"msg {i} " * 100} for i in range(12)]
    assert should_compact(msgs) is True


def test_should_compact_skips_short(monkeypatch):
    """Verify should_compact returns False for a short message list.

    Even with content, a 3-message session should NOT trigger compaction.
    """
    # Clear env override so we test the message-count floor (>=12) deterministically.
    monkeypatch.delenv("SAGE_COMPACT_THRESHOLD", raising=False)
    msgs = [{"role": "user", "content": "hi"} for _ in range(3)]
    assert should_compact(msgs) is False
