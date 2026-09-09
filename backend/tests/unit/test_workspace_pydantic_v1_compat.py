"""Pydantic v1/v2 compat regression test for ``backend.api.workspace_routes``.

The win7 LTS branch pins ``pydantic==1.10.13`` (last v1 release). Pydantic v2
syntax — ``model_config = ConfigDict(extra="forbid")`` — is **silently ignored**
on v1 (the attribute becomes a plain class attribute, not a model config), so
every request model that uses it accepts unknown fields instead of rejecting
them with 422. This is a correctness bug, not a crash, and it evades casual
testing because the v2 test env happily accepts both forms.

This test file pins the v1 semantics: every request/response model in
``workspace_routes`` that claims ``extra="forbid"`` must actually reject an
unknown field. On v2 the same test passes because both forms work; on v1 it
catches the silent-ignore regression.

See PR alpha.18-win7 (2026-09-10): ``model_config = ConfigDict(...)`` →
``class Config: extra = "forbid"`` (v1-compatible nested class form).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.api.workspace_routes import (
    WorkspaceBindingModel,
    WorkspaceBindingResponse,
    WorkspaceBindRequest,
    WorkspaceChangeEntryModel,
    WorkspaceChangesResponse,
    WorkspaceCheckpointCreateResponse,
    WorkspaceCheckpointModel,
    WorkspaceCheckpointRestoreRequest,
    WorkspaceCheckpointRestoreResponse,
    WorkspaceCheckpointsResponse,
    WorkspaceDiffResponse,
    WorkspaceRevertEntryModel,
    WorkspaceRevertHunksRequest,
    WorkspaceRevertHunksResponse,
    WorkspaceRevertRequest,
    WorkspaceRevertResponse,
    WorkspaceRevokeResponse,
    WorkspaceSearchResponse,
    WorkspaceSearchResultModel,
)

# Each tuple is ``(ModelClass, valid_kwargs, description)``. ``valid_kwargs``
# MUST satisfy all required fields; the test then re-invokes with an extra
# ``__pydantic_forbid_probe__=1`` kwarg and asserts ValidationError is raised.

_MODELS_WITH_VALID_KWARGS = [
    (WorkspaceBindingModel, {
        "session_id": "s", "workspace_path": "/w", "generation": 1,
        "activated_at": 0, "revoked_at": None,
    }, "binding"),
    (WorkspaceBindRequest, {"workspace_path": "/w"}, "bind request"),
    (WorkspaceBindingResponse, {"binding": None}, "binding response"),
    (WorkspaceRevertResponse, {
        "reverted": [], "errors": [],
    }, "revert response"),
    (WorkspaceRevertEntryModel, {"path": "/p", "error": "e"}, "revert entry"),
    (WorkspaceCheckpointModel, {
        "checkpoint_id": "c", "created_at": "2026-01-01T00:00:00Z",
        "bytes": 0, "files": None,
    }, "checkpoint model"),
    (WorkspaceCheckpointsResponse, {"checkpoints": []}, "checkpoints response"),
    (WorkspaceCheckpointCreateResponse, {
        "checkpoint_id": "c", "files": 0, "skipped": [], "bytes": 0,
    }, "create response"),
    (WorkspaceCheckpointRestoreRequest, {"checkpoint_id": "c"}, "restore request"),
    (WorkspaceCheckpointRestoreResponse, {
        "checkpoint_id": "c", "restored": 0,
    }, "restore response"),
    (WorkspaceSearchResultModel, {
        "name": "n", "kind": "k", "doc_type": None, "doc_id": None,
        "size_bytes": 0, "needs_import": False, "source_path": None,
    }, "search result model"),
    (WorkspaceSearchResponse, {"results": [], "total": 0}, "search response"),
    (WorkspaceChangeEntryModel, {
        "index_status": "s", "worktree_status": "s", "path": "/p",
    }, "change entry"),
    (WorkspaceChangesResponse, {
        "branch": "b", "upstream": "u", "ahead": 0, "behind": 0,
        "clean": True, "changes": [],
    }, "changes response"),
    (WorkspaceDiffResponse, {"diff": "", "truncated": False}, "diff response"),
    (WorkspaceRevertHunksRequest, {
        "path": "/p", "hunk_indices": [0],
    }, "revert hunks request"),
    (WorkspaceRevertHunksResponse, {
        "reverted_hunks": 0,
    }, "revert hunks response"),
    (WorkspaceRevokeResponse, {
        "revoked": False, "generation": 0,
    }, "revoke response"),
    (WorkspaceRevertRequest, {
        "paths": ["a"], "delete_untracked": False,
    }, "revert request"),
]


@pytest.mark.parametrize("model_cls,valid_kwargs,label", _MODELS_WITH_VALID_KWARGS)  # noqa: PT006
def test_workspace_model_rejects_extra_fields(
    model_cls: type, valid_kwargs: dict, label: str,
) -> None:
    """Each workspace model must reject unknown fields on pydantic v1 AND v2.

    This is the regression test for the silent-ignore bug: on v1, the v2-only
    ``model_config = ConfigDict(extra="forbid")`` form is a no-op — extra
    fields are silently accepted. The v1-compatible ``class Config: extra =
    "forbid"`` form works on both v1 and v2.
    """
    # Sanity: valid kwargs construct without error.
    model_cls(**valid_kwargs)

    # The actual forbid probe: adding an unknown field MUST raise ValidationError.
    with pytest.raises(ValidationError):
        model_cls(**valid_kwargs, __pydantic_forbid_probe__=1)  # type: ignore[call-arg]
