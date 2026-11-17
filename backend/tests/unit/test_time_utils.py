"""backend.memory.time_utils 的毫秒归一测试。"""

import time

from backend.memory.time_utils import (
    SECOND_LIKE_LIMIT,
    now_ms,
    seconds_to_ms,
    to_ms,
)


def test_now_ms_matches_wall_clock_milliseconds():
    before = int(time.time() * 1000)
    value = now_ms()
    after = int(time.time() * 1000)
    assert before <= value <= after


def test_to_ms_auto_treats_small_values_as_seconds():
    assert to_ms(1_700_000_000) == 1_700_000_000_000
    assert to_ms(1_700_000_000_000) == 1_700_000_000_000
    assert to_ms("1700000000") == 1_700_000_000_000
    assert SECOND_LIKE_LIMIT > 1_700_000_000_000 // 1000


def test_to_ms_force_unit():
    assert to_ms(1_700_000_000, assume="s") == 1_700_000_000_000
    assert to_ms(1_700_000_000_000, assume="ms") == 1_700_000_000_000


def test_to_ms_invalid_values_return_none():
    assert to_ms(None) is None
    assert to_ms("not-a-timestamp") is None
    assert to_ms(0) is None
    assert to_ms(-1) is None


def test_seconds_to_ms_alias():
    assert seconds_to_ms(1_700_000_000) == 1_700_000_000_000
    assert seconds_to_ms(None) is None
