"""Authorization for ChatOfficeRef in the legacy /chat/stream endpoint.

Task 6: Before ``StreamRegistry.create`` issues a stream id, the legacy
route must validate that every ``ChatOfficeRef`` the caller attached to
the chat request actually points at an Office document the chat session
has a live binding to. The route layer maps each domain error to an
HTTP status (see ``legacy_routes.chat_stream_create``); this module only
returns immutable values or raises :class:`WorkspaceBindingError`
subclasses.

Authorization rules:

1. ``office_refs=[]`` + no active binding      -> return ``None``
   Legacy fallback. Nothing to authorize; the route keeps the existing
   ``attachment_resolver`` path so old clients don't break.

1b. ``office_refs=[]`` + active binding         -> return
   :class:`AuthorizedOfficeRequest` with an empty ``office_doc_scope``.
   The binding generation is captured so downstream code can detect
   rebinds; no doc checks are needed because there are no refs.

2. ``office_refs=[..]`` + no session row         -> ``WorkspaceSessionNotFoundError``
   (404). The caller is using a session id that doesn't exist.

3. ``office_refs=[..]`` + no active binding      -> ``WorkspaceNotBoundError``
   (403). Refs require an active workspace binding; ``data.workspace_path``
   alone (the legacy field) is not authoritative.

4. ``office_refs=[..]`` + active binding:
   a. ``data.workspace_path`` set and != binding.workspace_path
      -> ``WorkspacePathMismatchError`` (400).
   b. For each ref, look up the doc by id within the binding's canonical
      workspace via :func:`get_document_in_workspace`. If the id lookup
      returns ``None``, fall back to :func:`find_document_by_filename`
      so the renderer-supplied ``@<filename>`` reference resolves to the
      managed UUID. On filename hit, the resolved id (not the filename)
      is the value appended to ``office_doc_scope``. Any of:
      - unknown doc id (and filename)
      - archived doc
      - type literal mismatch (when resolved via filename)
      -> ``WorkspaceDocumentNotFoundError`` (404) for id-lookup misses
      and ``WorkspacePathMismatchError`` (400) for filename-resolved
      type mismatches. The split is intentional: a type mismatch on a
      doc that exists but doesn't match the ref's claimed type is a
      400-shape mismatch, not a 404-not-found.

5. Happy path -> return :class:`AuthorizedOfficeRequest` with the binding
   generation captured and the canonical workspace path (backend-derived,
   never echoed from the caller).

Public surface:

    ChatOfficeRef                         # Pydantic DTO (strict)
    AuthorizedOfficeRequest               # frozen dataclass
    authorize_chat_office_request(...)    # raises or returns
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, List, Literal, Optional

from pydantic import BaseModel, Field

from backend.office.errors import OfficePathError
from backend.office.storage import validate_workspace

from .session_workspace import (
    find_document_by_filename,
    get_document_in_workspace,
    get_workspace_binding,
)
from .workspace_errors import (
    WorkspaceDocumentNotFoundError,
    WorkspaceNotBoundError,
    WorkspacePathMismatchError,
    WorkspaceSessionNotFoundError,
)

logger = logging.getLogger(__name__)

# Bound the doc id and filename to keep logs/keys sane and reject trivially
# malformed payloads at the API boundary. 256 chars is generous for a UUIDv4
# plus a filename extension and any path prefix the frontend might prepend.
_MAX_DOC_ID_LEN = 256
_MAX_FILENAME_LEN = 256

DocTypeLiteral = Literal["ppt", "word", "excel"]


class ChatOfficeRef(BaseModel):
    """A caller-supplied reference to an Office document in the workspace.

    Strict Pydantic v2 model — unknown fields are rejected (``extra='forbid'``)
    so a typo on the wire (e.g. ``docId`` vs ``doc_id``) becomes a 422 instead
    of being silently dropped. ``doc_type`` is a closed ``Literal`` set; any
    other value fails validation here and never reaches the authorization
    function.
    """

    class Config:
        extra = "forbid"

    doc_id: str = Field(min_length=1, max_length=_MAX_DOC_ID_LEN)
    doc_type: DocTypeLiteral
    filename: str = Field(min_length=1, max_length=_MAX_FILENAME_LEN)


@dataclass(frozen=True)
class AuthorizedOfficeRequest:
    """Result of a successful Office-ref authorization.

    Frozen dataclass so the route layer cannot mutate the scope after
    authorization — that would silently widen which docs the producer is
    allowed to load into the LLM context.

    Attributes:
        session_id: Chat session the refs were authorized for.
        binding_generation: The active binding's generation at authorization
            time. Captured so the downstream pipeline can detect rebinds.
        office_doc_scope: Set of doc ids the caller is allowed to attach.
            ``frozenset`` so the value is hashable and immutable.
        workspace_path: Backend-derived canonical workspace path (never
            echoed from the caller).
    """

    session_id: str
    binding_generation: int
    office_doc_scope: FrozenSet[str]
    workspace_path: str


def authorize_chat_office_request(
    conn: sqlite3.Connection,
    session_id: str,
    request_workspace_path: Optional[str],
    office_refs: List[ChatOfficeRef],
) -> Optional[AuthorizedOfficeRequest]:
    """Validate ``office_refs`` against the live session-workspace binding.

    Returns:
        ``None`` when there are no refs to authorize (legacy path).
        :class:`AuthorizedOfficeRequest` when every ref validates.

    Raises:
        WorkspaceSessionNotFoundError: session row absent and refs are
            non-empty.
        WorkspaceNotBoundError: refs are non-empty but the session has
            no active binding.
        WorkspacePathMismatchError: caller supplied a ``workspace_path``
            that doesn't match the active binding's canonical path.
        WorkspaceDocumentNotFoundError: a ref's doc id/type/filename
            doesn't match a live, non-archived document in the binding's
            workspace. Same exception class covers unknown / archived /
            type-mismatched / filename-mismatched cases so the route
            layer only needs one 404 mapping.
    """
    # Rule 1: legacy fallback. No refs AND no binding -> return None so the
    # route keeps the existing ``attachment_resolver`` path. If there IS an
    # active binding we still need to run the session-existence + binding
    # checks so the caller gets a captured generation + canonical workspace
    # path (binding generation matters for downstream rebind detection).
    if not office_refs:
        binding = get_workspace_binding(conn, session_id)
        if binding is None:
            return None
        # Active binding + empty refs: capture binding state, no doc checks.
        return AuthorizedOfficeRequest(
            session_id=session_id,
            binding_generation=binding.generation,
            office_doc_scope=frozenset(),
            workspace_path=binding.workspace_path,
        )

    # Rule 2: session existence check. We check this even when there's no
    # binding yet so a bad session id doesn't get a 200 + stream id leak.
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise WorkspaceSessionNotFoundError(
            f"Session '{session_id}' is not registered in the sessions table"
        )

    # Rule 3: require an active binding. ``get_workspace_binding`` returns
    # None for both unbound and revoked; the unified 403 message lets the
    # route layer distinguish via retry rather than the error class.
    binding = get_workspace_binding(conn, session_id)
    if binding is None:
        raise WorkspaceNotBoundError(
            f"Session '{session_id}' has no active workspace binding"
        )

    # Rule 4a: caller-supplied workspace_path must match the canonical
    # binding path. ``None`` is OK — the binding is authoritative.
    # The binding path is already canonical via validate_workspace().resolve()
    # at bind time (see session_workspace.bind_session_workspace), so we
    # canonicalize the caller-supplied path the same way before comparing
    # to avoid false mismatches from `./` segments, symlink targets, etc.
    if request_workspace_path is not None:
        try:
            caller_canonical = str(
                validate_workspace(Path(request_workspace_path))
            )
        except (OfficePathError, OSError):
            caller_canonical = request_workspace_path
        if caller_canonical != binding.workspace_path:
            raise WorkspacePathMismatchError(
                "Submitted workspace_path does not match the active binding"
            )

    # Rule 4b: validate every ref against the binding's canonical workspace.
    # Prefer the id-based lookup (renderer hands us a managed UUID when
    # it can). When the id misses, fall back to filename-based lookup
    # so chat ``@<filename>`` references resolve to the same UUID that
    # ``_persist_read_summary`` already wrote into the row.
    validated: List[str] = []
    for ref in office_refs:
        doc = get_document_in_workspace(conn, ref.doc_id, binding.workspace_path)
        resolved_via_filename = False
        if doc is None:
            doc = find_document_by_filename(
                conn, binding.workspace_path, ref.filename
            )
            if doc is None:
                # Covers unknown id + unknown filename, archived doc, and
                # cross-workspace lookups (the SQL scope filters
                # ``archived_at IS NULL`` and ``workspace_path = ?``).
                raise WorkspaceDocumentNotFoundError(
                    f"Office document '{ref.doc_id}' "
                    f"(filename '{ref.filename}') is not visible "
                    f"in the active workspace"
                )
            resolved_via_filename = True
        if doc.doc_type.value != ref.doc_type:
            # Filename-resolved hits raise 400 (the ref's declared type
            # disagrees with the actual doc); id-resolved hits keep the
            # existing 404 mapping for backward compatibility.
            if resolved_via_filename:
                raise WorkspacePathMismatchError(
                    f"Office document '{ref.filename}' resolved via "
                    f"filename lookup has type '{doc.doc_type.value}', "
                    f"but the reference declared '{ref.doc_type}'"
                )
            raise WorkspaceDocumentNotFoundError(
                f"Office document '{ref.doc_id}' type does not match the ref"
            )
        if doc.original_filename != ref.filename:
            raise WorkspaceDocumentNotFoundError(
                f"Office document '{ref.doc_id}' filename does not match the ref"
            )
        validated.append(doc.id)

    return AuthorizedOfficeRequest(
        session_id=session_id,
        binding_generation=binding.generation,
        office_doc_scope=frozenset(validated),
        workspace_path=binding.workspace_path,
    )
