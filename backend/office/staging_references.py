"""Read-only pre-cleanup evidence; never authorizes deletion.

Use the actual application's database, not a newly-created or copied empty DB.
A negative result covers only the named reference sources at one SQLite snapshot.
It is not a lease, an orphan proof, or protection against subsequent imports.
"""

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List


def inspect_references(
    database: Path, workspace: Path, doc_type: str, document_id: str
) -> Dict[str, Any]:
    """Inspect one managed directory without initializing DBs or touching files.

    ID matches deliberately retain across workspaces/types: duplicate IDs and
    stale workspace aliases should cause false retention, never false clearance.
    Missing schema, busy/corrupt databases and ambiguous paths return unknown.
    """
    result: Dict[str, Any] = {
        "read_only": True,
        "safe_to_delete": False,
        "status": "unknown",
        "references": [],
        "sources": [
            "office_documents.id",
            "office_documents.derived_from",
            "office_journal_generations.output_path",
        ],
    }
    if doc_type not in ("word", "ppt", "excel", "pdf") or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,128}", document_id
    ):
        result["error"] = "invalid_managed_reference"
        return result
    if not workspace.is_absolute() or not database.is_absolute():
        result["error"] = "absolute_paths_required"
        return result
    connection = None
    references: List[str] = result["references"]
    try:
        if not database.is_file() or not workspace.is_dir():
            raise ValueError("database_or_workspace_missing")
        directory = workspace / "office" / doc_type / document_id
        # Refuse links/aliases in the candidate hierarchy, including junctions.
        root = workspace.resolve(strict=True)
        resolved = directory.resolve()
        if resolved != root / "office" / doc_type / document_id:
            raise ValueError("linked_managed_directory")
        # mode=ro must not be replaced by immutable=1: live WAL must remain visible.
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        connection.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.execute("BEGIN")
        row = connection.execute(
            "SELECT 1 FROM office_documents WHERE lower(id) = lower(?) LIMIT 1",
            (document_id,),
        ).fetchone()
        if row:
            references.append("document_record_including_archived")
        row = connection.execute(
            "SELECT 1 FROM office_documents WHERE lower(derived_from) = lower(?) LIMIT 1",
            (document_id,),
        ).fetchone()
        if row:
            references.append("derived_document_lineage")
        cursor = connection.execute("SELECT output_path FROM office_journal_generations")
        for index, (output,) in enumerate(cursor):
            if index >= 10000 or time.monotonic() > deadline:
                raise ValueError("reference_scan_limit")
            if not isinstance(output, str) or not Path(output).is_absolute():
                raise ValueError("ambiguous_journal_path")
            output_path = Path(output).resolve()
            if (
                output_path == resolved or resolved in output_path.parents
            ) and "journal_output" not in references:
                references.append("journal_output")
        result["status"] = "referenced" if references else "no_reference_found"
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        # Preserve positive evidence even when another source cannot be read.
        result["status"] = "referenced" if references else "unknown"
        result["error"] = "incomplete_reference_check"
    finally:
        if connection is not None:
            connection.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--doc-type", required=True, choices=["word", "ppt", "excel", "pdf"])
    parser.add_argument("--document-id", required=True)
    args = parser.parse_args()
    report = inspect_references(args.database, args.workspace, args.doc_type, args.document_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))  # noqa: T201 -- CLI JSON output
    return 2 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
