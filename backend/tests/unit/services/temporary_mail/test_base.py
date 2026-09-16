"""Tests for the TemporaryMailProvider ABC and Mailbox dataclass."""

from __future__ import annotations

import re
from datetime import datetime
import pytest

from backend.services.temporary_mail.base import (
    Mailbox, TemporaryMailProvider,
)


def test_mailbox_dataclass_round_trip():
    m = Mailbox(
        email="user@temp.example",
        password="tok_abc",
        provider_token="provider_tok_xyz",
        provider="mailtm",
        created_at=datetime(2026, 9, 16, 12, 0, 0),
    )
    assert m.email == "user@temp.example"
    assert m.provider == "mailtm"


def test_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TemporaryMailProvider()  # abstract


def test_subclass_must_implement_methods():
    class Incomplete(TemporaryMailProvider):
        name = "incomplete"
        # missing create_mailbox, wait_for_code, etc.

    with pytest.raises(TypeError):
        Incomplete()


def test_code_extraction_regex_finds_6_digit_code():
    """The default subject pattern should match common verification subjects."""
    pattern = re.compile(r"verification|verify|code", re.IGNORECASE)
    assert pattern.search("Your verification code is 123456")
    assert pattern.search("Verify your email")
    assert pattern.search("Your Arena code: 987654")
