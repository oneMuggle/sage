# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Document revision identity for the office write path (F1, P0-A).

Every managed office document gets a *content* revision — a sha256 of the
bytes on disk — so that "what the user previewed" and "what the apply step
overwrites" can be proven to be the same version.

What this module is:

* ``compute_file_revision`` / ``compute_ops_hash`` / ``new_preview_id`` —
  the identifiers the preview returns and the apply step validates.
* ``document_write_lock`` — per-document, *in-process* serialization so
  "read revision → edit → persist" is one critical section.
* ``lookup_apply`` / ``remember_apply`` — a bounded, in-process idempotency
  ledger so a retried apply does not append the same content twice.

What this module is NOT (deliberately, see docs/plans/2026-09-26-office-doc-revision):

* Not a cross-process file lock. An external Word/WPS/editor does not honour
  ``document_write_lock``; the revision check is what catches those writes.
* Not durable state. The idempotency ledger lives in memory and is dropped on
  restart — a replay after restart degrades to a normal (still revision
  checked) write, never to a corrupted file.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .errors import OfficeFileNotFoundError

__all__ = [
    "REVISION_PREFIX",
    "compute_file_revision",
    "compute_ops_hash",
    "document_write_lock",
    "lookup_apply",
    "new_preview_id",
    "remember_apply",
    "stat_revision",
]

REVISION_PREFIX = "sha256:"
_CHUNK = 1024 * 1024
_IDEMPOTENCY_CAPACITY = 64
_MEMO_CAPACITY = 256

_locks_guard = threading.Lock()
_locks: Dict[str, threading.RLock] = {}

_ledger_guard = threading.Lock()
_ledger: OrderedDict[Tuple[str, str], Dict[str, Any]] = OrderedDict()

_memo_guard = threading.Lock()
_memo: OrderedDict[Tuple[str, int, int], str] = OrderedDict()


def compute_file_revision(path: Path) -> str:
    """Return ``sha256:<hex>`` for the bytes currently on disk.

    Streamed in 1MiB chunks — the office read cap is 20MB, so this stays in
    the tens-of-milliseconds range and never loads the file twice.

    Raises:
        OfficeFileNotFoundError: the file is missing (the caller's 404 path).
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise OfficeFileNotFoundError(file_path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return REVISION_PREFIX + digest.hexdigest()


def stat_revision(path: Path) -> str:
    """``compute_file_revision`` memoized on ``(path, size, mtime_ns)``.

    For the read-only ``GET /office/doc/{id}/revision`` probe the UI polls on
    every document switch: identical stat triple → identical bytes in every
    practical case, and a stale hit is impossible to observe because the
    write path always calls the unmemoized function inside the write lock.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise OfficeFileNotFoundError(file_path)
    stat = file_path.stat()
    key = (str(file_path), int(stat.st_size), int(getattr(stat, "st_mtime_ns", 0)))
    with _memo_guard:
        hit = _memo.get(key)
        if hit is not None:
            _memo.move_to_end(key)
            return hit
    revision = compute_file_revision(file_path)
    with _memo_guard:
        _memo[key] = revision
        _memo.move_to_end(key)
        while len(_memo) > _MEMO_CAPACITY:
            _memo.popitem(last=False)
    return revision


def compute_ops_hash(ops: List[Dict[str, Any]]) -> str:
    """Stable ``ops:<16hex>`` digest of an op batch.

    Key order must not change the hash (the UI serializes op dicts from
    React state), so the canonical form is ``sort_keys`` JSON. Non-JSON
    values degrade to ``repr`` rather than raising — this is an identifier,
    not a validator.
    """
    canonical = json.dumps(ops, sort_keys=True, ensure_ascii=False, default=repr)
    return "ops:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def new_preview_id() -> str:
    """Opaque id correlating a preview with the apply that follows it.

    Correlation/telemetry only — authorization stays with the doc row and
    the revision check; a guessed preview id grants nothing.
    """
    return "pv_" + uuid.uuid4().hex


@contextmanager
def document_write_lock(doc_id: str) -> Iterator[None]:
    """Serialize writes to one document *within this process*.

    Reentrant: the tool path and the API path may nest through the same
    helper without self-deadlocking.
    """
    with _locks_guard:
        lock = _locks.get(doc_id)
        if lock is None:
            lock = threading.RLock()
            _locks[doc_id] = lock
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def lookup_apply(doc_id: str, key: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the recorded outcome of a previous apply with this key."""
    if not key:
        return None
    with _ledger_guard:
        entry = _ledger.get((doc_id, key))
        if entry is None:
            return None
        _ledger.move_to_end((doc_id, key))
        return dict(entry)


def remember_apply(
    doc_id: str,
    key: Optional[str],
    revision_before: str,
    revision_after: str,
    payload: Any,
) -> None:
    """Record an apply outcome so an identical retry can replay it."""
    if not key:
        return
    with _ledger_guard:
        _ledger[(doc_id, key)] = {
            "revision_before": revision_before,
            "revision_after": revision_after,
            "payload": payload,
        }
        _ledger.move_to_end((doc_id, key))
        while len(_ledger) > _IDEMPOTENCY_CAPACITY:
            _ledger.popitem(last=False)


def _reset_for_tests() -> None:
    """Drop all in-process state (tests only; never called by product code)."""
    with _ledger_guard:
        _ledger.clear()
    with _memo_guard:
        _memo.clear()
