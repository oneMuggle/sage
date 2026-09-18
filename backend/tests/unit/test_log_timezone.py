"""Unit tests for log timezone formatting (2026-09-17).

Tests TimezoneFormatter and set_log_timezone() in backend/utils/logging.py.
"""
from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _reset_timezone():
    """Reset timezone to UTC after each test."""
    yield
    from backend.utils.logging import set_log_timezone
    set_log_timezone("UTC")


class TestTimezoneFormatter:
    """TimezoneFormatter renders timestamps in the configured timezone."""

    def test_default_utc(self):
        """Default formatter produces UTC timestamps."""
        from backend.utils.logging import TimezoneFormatter
        fmt = TimezoneFormatter("%(asctime)s", "%Y-%m-%dT%H:%M:%S")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.created = 1700000000.0  # 2023-11-14T22:13:20 UTC
        output = fmt.formatTime(record)
        assert "2023-11-14T22:13:20" in output

    def test_asia_shanghai(self):
        """Asia/Shanghai formatter produces +08:00 timestamps."""
        from backend.utils.logging import TimezoneFormatter, set_log_timezone
        set_log_timezone("Asia/Shanghai")
        fmt = TimezoneFormatter("%(asctime)s", "%Y-%m-%dT%H:%M:%S")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        # 2023-11-14T22:13:20 UTC = 2023-11-15T06:13:20 +08:00
        record.created = 1700000000.0
        output = fmt.formatTime(record)
        assert "2023-11-15T06:13:20" in output

    def test_local_timezone(self):
        """'local' uses system local timezone without error."""
        from backend.utils.logging import TimezoneFormatter, set_log_timezone
        set_log_timezone("local")
        fmt = TimezoneFormatter("%(asctime)s", "%Y-%m-%dT%H:%M:%S")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.created = 1700000000.0
        output = fmt.formatTime(record)
        # Should not raise; exact output depends on system timezone
        assert "2023-11-" in output

    def test_invalid_timezone_falls_back_to_utc(self):
        """Invalid IANA timezone falls back to UTC."""
        from backend.utils.logging import TimezoneFormatter, set_log_timezone
        set_log_timezone("Invalid/Timezone")
        fmt = TimezoneFormatter("%(asctime)s", "%Y-%m-%dT%H:%M:%S")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.created = 1700000000.0
        output = fmt.formatTime(record)
        assert "2023-11-14T22:13:20" in output

    def test_switch_timezone(self):
        """Switching timezone affects subsequent records."""
        from backend.utils.logging import TimezoneFormatter, set_log_timezone
        fmt = TimezoneFormatter("%(asctime)s", "%Y-%m-%dT%H:%M:%S")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.created = 1700000000.0

        set_log_timezone("UTC")
        utc_output = fmt.formatTime(record)

        set_log_timezone("Asia/Tokyo")  # +09:00
        tokyo_output = fmt.formatTime(record)

        assert "2023-11-14T22:13:20" in utc_output
        assert "2023-11-15T07:13:20" in tokyo_output


class TestSetLogTimezone:
    """set_log_timezone() updates the global timezone."""

    def test_set_valid_timezone(self):
        import backend.utils.logging as mod
        from backend.utils.logging import set_log_timezone
        set_log_timezone("America/New_York")
        assert mod._CURRENT_LOG_TIMEZONE == "America/New_York"

    def test_set_empty_string_ignored(self):
        import backend.utils.logging as mod
        from backend.utils.logging import set_log_timezone
        set_log_timezone("UTC")
        set_log_timezone("")
        assert mod._CURRENT_LOG_TIMEZONE == "UTC"

    def test_set_none_ignored(self):
        import backend.utils.logging as mod
        from backend.utils.logging import set_log_timezone
        set_log_timezone("UTC")
        set_log_timezone(None)  # type: ignore[arg-type]
        assert mod._CURRENT_LOG_TIMEZONE == "UTC"
