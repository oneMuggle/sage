# ruff: noqa: UP006, UP007, UP035 — Python 3.8 typing compatibility
"""Unit tests for scripts/check_silent_exceptions.py and core subsystem zero-ceiling ratchet (L3)."""

from __future__ import annotations

import pytest
from scripts.check_silent_exceptions import (
    BASELINE_PATH,
    REPO_ROOT,
    load_baseline,
    scan_backend,
    scan_source,
)

pytestmark = pytest.mark.unit


def test_scan_source_flags_only_broad_silent_handlers() -> None:
    sample = """
try:
    do_work()
except Exception:
    pass

try:
    do_work()
except BaseException:
    ...

try:
    do_work()
except ValueError:
    pass

try:
    do_work()
except Exception as exc:
    logger.debug("logged: %s", exc)
"""
    hits = scan_source(sample, "backend/chat/sample.py")
    assert hits == [
        ("backend/chat/sample.py", 4, "Exception"),
        ("backend/chat/sample.py", 9, "BaseException"),
    ]


def test_core_subsystems_have_zero_silent_broad_exceptions() -> None:
    counts, _ = scan_backend(REPO_ROOT)
    baseline = load_baseline(BASELINE_PATH)

    for zero_sub in (
        "backend/application",
        "backend/chat",
        "backend/data",
        "backend/domain",
        "backend/orchestration",
    ):
        assert baseline.get(zero_sub) == 0, f"{zero_sub} ceiling must be 0"
        assert counts.get(zero_sub, 0) == 0, f"{zero_sub} has silent broad except-pass"

    for sub, count in counts.items():
        assert count <= baseline.get(sub, 0), f"{sub} exceeded baseline ceiling"
