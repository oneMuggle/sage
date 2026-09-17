"""Tests for Message dataclass fields added for context-isolation (segment_id, subtype)."""

from backend.data.session_repo import Message


def test_message_default_segment_zero():
    """Message defaults: segment_id=0, subtype=None."""
    msg = Message(
        id="msg-1",
        session_id="s1",
        role="user",
        content="hi",
        created_at=1234567890,
    )
    assert msg.segment_id == 0
    assert msg.subtype is None


def test_message_explicit_segment_and_subtype():
    """Message accepts explicit segment_id and subtype."""
    msg = Message(
        id="msg-1",
        session_id="s1",
        role="system",
        content="reset",
        created_at=1,
        segment_id=2,
        subtype="topic_separator",
    )
    assert msg.segment_id == 2
    assert msg.subtype == "topic_separator"
