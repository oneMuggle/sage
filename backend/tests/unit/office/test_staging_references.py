"""Reference evidence must fail closed and must never become a delete decision."""

import sqlite3

import pytest

from backend.office.staging_references import inspect_references


@pytest.fixture()
def state(tmp_path):
    db = tmp_path / "sage.db"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with sqlite3.connect(str(db)) as conn:
        conn.executescript("""
            CREATE TABLE office_documents (id TEXT, derived_from TEXT, archived_at INTEGER);
            CREATE TABLE office_journal_generations (output_path TEXT);
        """)
    return db, workspace


def check(state):
    return inspect_references(*state, "word", "import-123")


def test_missing_db_is_not_created(tmp_path):
    db = tmp_path / "missing.db"
    result = inspect_references(db, tmp_path, "word", "import-123")
    assert result["status"] == "unknown"
    assert not result["safe_to_delete"]
    assert not db.exists()


@pytest.mark.parametrize("archived", [None, 123])
def test_live_and_archived_documents_are_retained(state, archived):
    with sqlite3.connect(str(state[0])) as conn:
        conn.execute("INSERT INTO office_documents VALUES (?, NULL, ?)", ("import-123", archived))
    before = state[0].read_bytes()
    result = check(state)
    assert result["status"] == "referenced"
    assert result["references"] == ["document_record_including_archived"]
    assert state[0].read_bytes() == before
    assert not result["safe_to_delete"]


def test_derived_document_retains_missing_parent(state):
    with sqlite3.connect(str(state[0])) as conn:
        conn.execute("INSERT INTO office_documents VALUES ('child', 'IMPORT-123', 123)")
    assert check(state)["references"] == ["derived_document_lineage"]


def test_journal_path_boundary(state):
    directory = state[1] / "office" / "word" / "import-123"
    with sqlite3.connect(str(state[0])) as conn:
        conn.execute(
            "INSERT INTO office_journal_generations VALUES (?)",
            (str(directory.parent / "import-123-other" / "doc.docx"),),
        )
    assert check(state)["status"] == "no_reference_found"
    with sqlite3.connect(str(state[0])) as conn:
        conn.execute(
            "INSERT INTO office_journal_generations VALUES (?)", (str(directory / "doc.docx"),)
        )
    assert check(state)["references"] == ["journal_output"]


def test_negative_result_never_authorizes_deletion(state):
    before = state[0].read_bytes()
    result = check(state)
    assert result["status"] == "no_reference_found"
    assert result["safe_to_delete"] is False
    assert state[0].read_bytes() == before
    assert list(state[1].iterdir()) == []


def test_missing_schema_is_unknown_not_empty(state):
    with sqlite3.connect(str(state[0])) as conn:
        conn.execute("DROP TABLE office_journal_generations")
    assert check(state)["status"] == "unknown"


def test_positive_evidence_survives_partial_failure(state):
    with sqlite3.connect(str(state[0])) as conn:
        conn.execute("INSERT INTO office_documents VALUES ('import-123', NULL, NULL)")
        conn.execute("DROP TABLE office_journal_generations")
    result = check(state)
    assert result["status"] == "referenced"
    assert "error" in result


@pytest.mark.parametrize("value", [None, "relative/file.docx"])
def test_ambiguous_journal_reference_is_unknown(state, value):
    with sqlite3.connect(str(state[0])) as conn:
        conn.execute("INSERT INTO office_journal_generations VALUES (?)", (value,))
    assert check(state)["status"] == "unknown"


def test_invalid_candidate_is_rejected(state):
    assert inspect_references(*state, "word", "../victim")["status"] == "unknown"


def test_corrupt_database_is_retained(state):
    state[0].write_bytes(b"not a sqlite database")
    assert check(state)["status"] == "unknown"


def test_live_wal_commit_is_visible(state):
    conn = sqlite3.connect(str(state[0]))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO office_documents VALUES ('import-123', NULL, NULL)")
        conn.commit()
        assert check(state)["status"] == "referenced"
    finally:
        conn.close()


def test_locked_database_is_unknown(state):
    conn = sqlite3.connect(str(state[0]))
    try:
        conn.execute("BEGIN EXCLUSIVE")
        assert check(state)["status"] == "unknown"
    finally:
        conn.close()


def test_scan_limit_is_unknown(state):
    with sqlite3.connect(str(state[0])) as conn:
        conn.executemany(
            "INSERT INTO office_journal_generations VALUES (?)",
            [(str(state[1] / "other.docx"),)] * 10001,
        )
    assert check(state)["status"] == "unknown"


def test_relative_inputs_are_unknown(state):
    from pathlib import Path

    assert (
        inspect_references(Path("relative.db"), state[1], "word", "import-123")["status"]
        == "unknown"
    )
