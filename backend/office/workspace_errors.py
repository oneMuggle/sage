"""Session-workspace binding exception hierarchy.

Domain errors raised by :mod:`backend.office.session_workspace` when a binding
operation fails. All errors inherit from ``WorkspaceBindingError`` and expose
a ``safe_message`` attribute that NEVER echoes back a submitted absolute
path — callers in the routes layer log ``exc.safe_message`` rather than
``str(exc)`` so we don't leak filesystem layout to logs or HTTP bodies.

Error → HTTP status mapping (handled by the routes layer):
- WorkspaceSessionNotFoundError        → 404
- WorkspaceNotBoundError               → 409 (no active binding for session)
- WorkspaceRevokedError                → 410 (binding was revoked)
- WorkspaceGenerationMismatchError     → 409 (caller is using stale gen)
- WorkspacePathMismatchError           → 409 (workspace no longer matches)
- WorkspaceDocumentNotFoundError       → 404
- WorkspaceBindingError (base)         → 500 (catch-all)
"""

from __future__ import annotations


class WorkspaceBindingError(Exception):
    """Base class for all session-workspace binding errors."""

    code = "workspace_binding_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.safe_message = message


class WorkspaceSessionNotFoundError(WorkspaceBindingError):
    """The chat session id does not exist in the sessions table."""

    code = "session_not_found"


class WorkspaceNotBoundError(WorkspaceBindingError):
    """The session has no active workspace binding (or never had one)."""

    code = "workspace_not_bound"


class WorkspaceRevokedError(WorkspaceBindingError):
    """The session's binding was explicitly revoked (tombstoned)."""

    code = "workspace_revoked"


class WorkspaceGenerationMismatchError(WorkspaceBindingError):
    """The caller supplied an expected_generation that no longer matches."""

    code = "workspace_generation_mismatch"


class WorkspacePathMismatchError(WorkspaceBindingError):
    """The submitted workspace_path differs from the active binding's path."""

    code = "workspace_path_mismatch"


class WorkspaceDocumentNotFoundError(WorkspaceBindingError):
    """The document id does not exist (or is archived) in the given workspace."""

    code = "document_not_found"
