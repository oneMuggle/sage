"""Import duplicate detection for the office module (AI workbench, Phase 0).

Re-importing the same file must not silently create a second document.
This router answers the question "which documents already in this
workspace hold the same bytes as the file I am about to import?" — the
renderer then offers the user three actions:

1. open the existing document,
2. import as a new version of it (``derived_from`` is set),
3. import an independent copy.

The digest is always computed server-side from the on-disk bytes; the
renderer never supplies a hash we would have to trust.

The router is mounted as a sibling of the other office sub-routers (it
is included by ``office_routes.router``, whose prefix is ``/office``),
so the paths below resolve to ``/api/v1/office/documents/...``.

Python 3.8-compatible (``typing.List``/``Optional``, no PEP 585/604
syntax) so this module can be cherry-picked to ``release/win7`` unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import get_database
from backend.office.errors import OfficeFileNotFoundError, OfficePathError
from backend.office.models import OfficeDocumentSummary
from backend.office.path_safety import resolve_within, validate_doc_id
from backend.office.revision import compute_file_revision
from backend.office.storage import (
    ensure_content_hash_table,
    find_documents_by_hash,
    get_document,
    list_duplicate_groups,
    set_document_lineage,
    validate_workspace,
)

router = APIRouter(prefix="/documents", tags=["office"])

#: Upper bound on the files checked in one request. The import path stages
#: a handful of files at a time; a huge batch would only slow the
#: pre-flight down (each file is streamed through SHA-256).
MAX_DUPLICATE_CHECK_FILES = 50


class OfficeDuplicateCheckRequest(BaseModel):
    """Ask which imported documents share the bytes of the given files."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(description="Absolute path to the workspace dir")
    file_paths: List[str] = Field(
        default_factory=list,
        description="Absolute paths of the files about to be imported",
    )


class OfficeDuplicateCheckEntry(BaseModel):
    """One requested file plus the documents whose bytes it duplicates.

    The result list is POSITIONAL: entry *i* corresponds to request file
    *i*, so the renderer can pair staged files with their matches without
    relying on path-string equality (the resolved path may differ from the
    path the renderer sent when a symlink is involved).
    """

    model_config = ConfigDict(extra="forbid")

    file_path: str
    content_hash: Optional[str] = Field(
        default=None,
        description="Digest of the staged file; null when it is not on disk",
    )
    duplicates: List[OfficeDocumentSummary] = Field(default_factory=list)


class OfficeDuplicateCheckResult(BaseModel):
    """One entry per requested file, in request order."""

    model_config = ConfigDict(extra="forbid")

    files: List[OfficeDuplicateCheckEntry] = Field(default_factory=list)


class OfficeDuplicateGroup(BaseModel):
    """Live documents in one workspace that share identical bytes."""

    model_config = ConfigDict(extra="forbid")

    content_hash: str
    documents: List[OfficeDocumentSummary] = Field(default_factory=list)


class OfficeDuplicateGroupsResult(BaseModel):
    """All duplicate groups in a workspace, newest group first."""

    model_config = ConfigDict(extra="forbid")

    groups: List[OfficeDuplicateGroup] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)


class OfficeDocumentLineageRequest(BaseModel):
    """Set (or clear) the upstream document of an imported document."""

    model_config = ConfigDict(extra="forbid")

    derived_from: Optional[str] = Field(
        default=None,
        description="Id of the document this one was derived from; null clears it",
    )


class OfficeDocumentLineageResponse(BaseModel):
    """Result of a lineage update."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    derived_from: Optional[str] = None
    updated: bool = False


@router.post("/duplicates", response_model=OfficeDuplicateCheckResult)
def check_duplicates_endpoint(
    req: OfficeDuplicateCheckRequest,
) -> OfficeDuplicateCheckResult:
    """Report which imported documents share the bytes of the given files.

    SECURITY: every path is resolved inside the workspace sandbox — a path
    that escapes the workspace is rejected with 400 instead of being hashed.

    The response is positional: ``result.files[i]`` answers
    ``req.file_paths[i]``. A file that is not on disk comes back with
    ``content_hash=None`` and no duplicates — the subsequent read step is
    what reports the real error for it.
    """
    if len(req.file_paths) > MAX_DUPLICATE_CHECK_FILES:
        raise OfficePathError(
            f"Too many files in one duplicate check: {len(req.file_paths)} (max {MAX_DUPLICATE_CHECK_FILES})"
        )
    workspace = validate_workspace(req.workspace_path)
    canonical_workspace = str(workspace.resolve())
    conn = get_database().get_connection()
    ensure_content_hash_table(conn)

    entries: List[OfficeDuplicateCheckEntry] = []
    for raw_path in req.file_paths:
        target = resolve_within(workspace, Path(raw_path))
        if not target.is_file():
            entries.append(OfficeDuplicateCheckEntry(file_path=str(target)))
            continue
        content_hash = compute_file_revision(target)
        duplicates = find_documents_by_hash(conn, canonical_workspace, content_hash)
        entries.append(
            OfficeDuplicateCheckEntry(
                file_path=str(target),
                content_hash=content_hash,
                duplicates=duplicates,
            )
        )
    return OfficeDuplicateCheckResult(files=entries)


@router.get("/duplicate-groups", response_model=OfficeDuplicateGroupsResult)
def list_duplicate_groups_endpoint(
    workspace_path: str,
) -> OfficeDuplicateGroupsResult:
    """List groups of live documents whose bytes are identical.

    Powers the document library's duplicate badge + "keep newest, archive
    the rest" cleanup action (Phase 1 Item A). Only groups with two or more
    live documents are returned; documents imported before content hashing
    existed are never reported as duplicates.
    """
    workspace = validate_workspace(workspace_path)
    canonical_workspace = str(workspace.resolve())
    conn = get_database().get_connection()
    groups = list_duplicate_groups(conn, canonical_workspace)
    return OfficeDuplicateGroupsResult(
        groups=[
            OfficeDuplicateGroup(content_hash=digest, documents=documents)
            for digest, documents in groups
        ],
        total=len(groups),
    )


@router.post("/{doc_id}/lineage", response_model=OfficeDocumentLineageResponse)
def set_document_lineage_endpoint(
    doc_id: str,
    req: OfficeDocumentLineageRequest,
) -> OfficeDocumentLineageResponse:
    """Record that a document was derived from another one.

    Used by the "import as a new version" branch of the duplicate dialog:
    the newly imported document keeps its own bytes but points at the
    document it supersedes, so the history view can show the lineage.
    """
    validate_doc_id(doc_id)
    conn = get_database().get_connection()
    if req.derived_from is not None:
        validate_doc_id(req.derived_from)
        if get_document(conn, req.derived_from) is None:
            raise OfficeFileNotFoundError(
                Path(req.derived_from),
                message=f"Source document not found: {req.derived_from}",
            )
    updated = set_document_lineage(conn, doc_id, req.derived_from)
    if not updated:
        raise OfficeFileNotFoundError(
            Path(doc_id),
            message=f"Document not found: {doc_id}",
        )
    return OfficeDocumentLineageResponse(
        document_id=doc_id,
        derived_from=req.derived_from,
        updated=True,
    )
