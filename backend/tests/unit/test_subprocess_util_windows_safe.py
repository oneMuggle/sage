"""Regression: ``os.O_NONBLOCK`` is POSIX-only and missing on Windows.

Both ``BoundedOutputCollector._open_output`` and ``read_capped_output`` in
``backend.tools.subprocess_util`` originally referenced ``os.O_NONBLOCK``
unconditionally, causing the bash tool to crash on Windows with::

    AttributeError: module 'os' has no attribute 'O_NONBLOCK'

This file lives outside ``test_subprocess_util.py`` / ``test_bash_session.py``
on purpose: those two files are skipped wholesale on Windows because their
existing tests rely on POSIX-only fixtures (process groups, ``os.pipe()``).
The two tests here deliberately touch only the cross-platform code path and
exercise it by ``monkeypatch.delattr``-ing ``os.O_NONBLOCK``, which makes
them run identically on Linux CI and the Win7 LTS CI job.
"""

from __future__ import annotations

import io
import os

import pytest

from backend.tools.subprocess_util import (
    BoundedOutputCollector,
    read_capped_output,
)


def _drop_nonblock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the Windows build of CPython, where ``os.O_NONBLOCK`` is absent."""
    monkeypatch.delattr("os.O_NONBLOCK", raising=False)


def test_collector_open_output_skips_missing_os_nonblock(tmp_path, monkeypatch):
    """``BoundedOutputCollector._open_output`` must not raise AttributeError
    when ``os.O_NONBLOCK`` is unavailable. Writes go to a regular file, so
    non-blocking mode is irrelevant on the write side.
    """
    _drop_nonblock(monkeypatch)

    collector = BoundedOutputCollector(
        io.BytesIO(b"hello"), str(tmp_path / "out"), max_bytes=64
    )
    # Trigger eagerly so the test fails fast rather than racing with the
    # collector worker thread.
    collector._open_output()  # noqa: SLF001 — regression probe


def test_read_capped_output_skips_missing_os_nonblock(tmp_path, monkeypatch):
    """``read_capped_output`` must fall back to a blocking regular-file read
    when ``os.O_NONBLOCK`` is unavailable (the production Windows case).
    """
    _drop_nonblock(monkeypatch)
    f = tmp_path / "out.out"
    f.write_bytes(b"\x1b[32mhello\x1b[0m world")
    text, truncated, _ = read_capped_output(str(f), cap=1024)
    assert text == "hello world"
    assert truncated is False


def test_drop_nonblock_helper_removes_attribute_on_any_platform(monkeypatch):
    """``_drop_nonblock`` must succeed on every platform — on POSIX it removes
    the attribute, on Windows it is a no-op because the attribute is already
    absent. Both branches exercise the contract the production code relies on.
    """
    # Whether ``os.O_NONBLOCK`` was present before the helper ran depends on
    # the host (POSIX: present; Windows: absent). After the helper, it must
    # always be gone.
    _drop_nonblock(monkeypatch)
    assert not hasattr(os, "O_NONBLOCK")
