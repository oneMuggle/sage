"""Unit tests for backend.office.revision (F1 — document version identity).

Pure helpers only: hashing, op digests, the in-process write lock and the
bounded idempotency ledger. The end-to-end "stale apply is refused" story
lives in tests/integration/test_office_revision_guard.py.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend.office import revision as rev
from backend.office.errors import OfficeFileNotFoundError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_state():
    rev._reset_for_tests()
    yield
    rev._reset_for_tests()


def test_file_revision_is_stable_and_content_sensitive(tmp_path: Path):
    target = tmp_path / "a.bin"
    target.write_bytes(b"hello")
    first = rev.compute_file_revision(target)

    assert first.startswith(rev.REVISION_PREFIX)
    assert rev.compute_file_revision(target) == first

    # Same byte LENGTH, different content — the exact collision the old
    # ``id:file_size_bytes`` cache key could not see (F2).
    target.write_bytes(b"world")
    assert rev.compute_file_revision(target) != first


def test_file_revision_missing_file_raises_not_found(tmp_path: Path):
    with pytest.raises(OfficeFileNotFoundError):
        rev.compute_file_revision(tmp_path / "nope.docx")


def test_stat_revision_memoizes_but_follows_content_change(tmp_path: Path):
    target = tmp_path / "b.bin"
    target.write_bytes(b"one")
    first = rev.stat_revision(target)
    assert rev.stat_revision(target) == first == rev.compute_file_revision(target)

    target.write_bytes(b"two-different-length")
    assert rev.stat_revision(target) == rev.compute_file_revision(target)


def test_ops_hash_ignores_key_order_but_not_values():
    a = rev.compute_ops_hash([{"op": "replace_text", "find": "x", "replace": "y"}])
    b = rev.compute_ops_hash([{"replace": "y", "find": "x", "op": "replace_text"}])
    c = rev.compute_ops_hash([{"op": "replace_text", "find": "x", "replace": "z"}])

    assert a == b
    assert a != c
    assert a.startswith("ops:")


def test_ops_hash_survives_non_json_values():
    assert rev.compute_ops_hash([{"op": "x", "blob": object()}]).startswith("ops:")


def test_preview_ids_are_unique():
    assert rev.new_preview_id() != rev.new_preview_id()


def test_write_lock_serializes_and_is_reentrant():
    order: list = []
    holding = threading.Event()
    release = threading.Event()

    def first():
        with rev.document_write_lock("doc-1"):
            # Reentrancy: the API path may nest through the tool path.
            with rev.document_write_lock("doc-1"):
                order.append("first-in")
            holding.set()
            release.wait(timeout=5)
            order.append("first-out")

    def second():
        holding.wait(timeout=5)
        with rev.document_write_lock("doc-1"):
            order.append("second-in")

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    holding.wait(timeout=5)
    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert order == ["first-in", "first-out", "second-in"]


def test_different_documents_do_not_block_each_other():
    with rev.document_write_lock("doc-a"):
        done = threading.Event()

        def other():
            with rev.document_write_lock("doc-b"):
                done.set()

        thread = threading.Thread(target=other)
        thread.start()
        assert done.wait(timeout=5) is True
        thread.join(timeout=5)


def test_ledger_roundtrip_and_key_scoping():
    rev.remember_apply("doc-1", "key-1", "sha256:before", "sha256:after", {"ok": True})

    hit = rev.lookup_apply("doc-1", "key-1")
    assert hit is not None
    assert hit["revision_before"] == "sha256:before"
    assert hit["revision_after"] == "sha256:after"

    assert rev.lookup_apply("doc-2", "key-1") is None
    assert rev.lookup_apply("doc-1", "other") is None
    assert rev.lookup_apply("doc-1", None) is None


def test_ledger_without_key_records_nothing():
    rev.remember_apply("doc-1", None, "a", "b", {"ok": True})
    assert rev.lookup_apply("doc-1", None) is None


def test_ledger_is_bounded_and_evicts_oldest():
    capacity = rev._IDEMPOTENCY_CAPACITY
    for i in range(capacity + 5):
        rev.remember_apply("doc-1", f"key-{i}", "a", "b", {"i": i})

    assert rev.lookup_apply("doc-1", "key-0") is None
    assert rev.lookup_apply("doc-1", f"key-{capacity + 4}") is not None
