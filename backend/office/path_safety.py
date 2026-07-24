"""Cross-platform path-safety primitives for the Office module.

The Office workspace sandbox (see plan §6 R1) must guard every untrusted
file path against:

- ``..`` traversal segments
- absolute paths outside the workspace
- **sibling-prefix** collisions (``/tmp/work-evil`` vs ``/tmp/work``)
- symlink escapes

The previous implementation used ``str.startswith(workspace_str + "/")``
which silently allowed sibling-prefix traversal because OS-level
``..`` collapse is not performed on a string. ``PurePath.relative_to``
raises ``ValueError`` for non-children, which is the correct semantic
boundary — we delegate to it on the **resolved** path and never compare
strings.

All helpers are pure stdlib. **Python 3.8-compatible syntax** (no PEP 604
``X | None``, no ``list[int]`` annotation, no ``:=`` walrus) so this
module can be cherry-picked to ``release/win7`` later without a separate
backport branch.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePath

from .errors import OfficePathError
from .models import OfficeDocType

# Reuse the exact regex already enforced by the storage layer.
_DOC_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# Map OfficeDocType -> canonical lowercase extension (no leading dot).
_DOC_TYPE_EXTENSIONS = {
    OfficeDocType.PPT: "pptx",
    OfficeDocType.WORD: "docx",
    OfficeDocType.EXCEL: "xlsx",
}


def is_within(base: PurePath, candidate: PurePath) -> bool:
    """Return ``True`` iff ``candidate`` lies within ``base``.

    Both arguments are ``PurePath`` subclasses — the caller picks
    ``PurePosixPath`` or ``PureWindowsPath`` to choose the flavor. This
    keeps the helper testable on either platform without touching the
    actual filesystem.

    Implementation note: never compare ``str(base)`` prefixes. Sibling
    directories like ``/tmp/work-evil`` share a common string prefix with
    ``/tmp/work`` but are NOT children. ``PurePath.relative_to`` raises
    ``ValueError`` for non-children, which is the precise semantic we
    want — identical to ``Path.is_relative_to()`` but available on 3.8+.
    """
    try:
        candidate.relative_to(base)
    except ValueError:
        return False
    return True


def resolve_within(base: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` against the filesystem and verify it lies in ``base``.

    Resolution collapses ``..`` segments and follows symlinks, so by the
    time we call :func:`is_within` we've eliminated:

    - ``../`` traversal (``Path.resolve`` walks the actual fs).
    - symlink-based escapes (resolved symlinks that point outside ``base``
      fail ``relative_to``).

    Raises:
        OfficePathError: if the resolved path escapes ``base`` for any of
        the reasons above (or if resolution fails for an OS reason).
    """
    resolved_base = base.resolve()
    try:
        resolved_candidate = candidate.resolve()
    except OSError as exc:
        # ``Path.resolve`` may raise on missing files or OS-level limits;
        # map every variant to OfficePathError so the route layer returns
        # 400 rather than 500.
        raise OfficePathError(
            f"Failed to resolve path {candidate!s}: {exc}",
            file_path=candidate,
        ) from exc

    if not is_within(resolved_base, resolved_candidate):
        raise OfficePathError(
            "Path is not within base workspace: resolved candidate "
            f"{resolved_candidate!s} is not inside {resolved_base!s}",
            file_path=resolved_candidate,
        )
    return resolved_candidate


def validate_supported_filename(filename: str, doc_type: OfficeDocType) -> str:
    """Validate a user-supplied filename and ensure it carries the right extension.

    Rules:

    - No path separators (forward or backward slash).
    - No ``..`` parent-traversal markers.
    - Extension (case-insensitive) must match the ``doc_type``.

    If ``filename`` is missing the extension it is appended automatically
    to preserve the existing convenience behavior of ``ppt._safe_filename``.
    """
    if "/" in filename or "\\" in filename:
        raise OfficePathError(
            f"Filename contains path separator: {filename!r}",
        )
    if ".." in filename:
        raise OfficePathError(
            f"Filename contains '..' segment: {filename!r}",
        )

    expected_ext = _DOC_TYPE_EXTENSIONS[doc_type]
    lowered = filename.lower()

    # Detect the actual extension (text after the last '.'). If there is
    # one and it doesn't match the doc type's canonical extension,
    # reject — never silently rewrite a wrong extension. Only auto-append
    # when the basename has no extension at all.
    basename_lower = lowered.rsplit("/", 1)[-1]
    if "." in basename_lower:
        actual_ext = basename_lower.rsplit(".", 1)[1]
        if actual_ext != expected_ext:
            raise OfficePathError(
                f"Filename extension {actual_ext!r} does not match "
                f"doc type {doc_type.value!r} (expected {expected_ext!r}): "
                f"{filename!r}",
            )
    else:
        # Auto-append missing extension only when none was supplied.
        filename = filename + "." + expected_ext
    return filename


def _validate_doc_id(document_id: str) -> str:
    """Enforce the doc-id regex; raise OfficePathError on mismatch."""
    if not _DOC_ID_PATTERN.match(document_id):
        raise OfficePathError(
            "document_id contains unsafe characters "
            f"(must match {_DOC_ID_PATTERN.pattern}): {document_id!r}",
        )
    return document_id


def validate_doc_id(document_id: str) -> str:
    """Public re-export of :func:`_validate_doc_id`.

    Exists so the storage layer can enforce the same doc-id regex that
    :func:`managed_document_path` uses without re-declaring
    ``_DOC_ID_PATTERN``. The previous layout duplicated the regex in
    ``storage.py`` and ``path_safety.py``, which silently diverged
    during refactors; one source of truth now lives in this module.
    """
    return _validate_doc_id(document_id)


def managed_document_directory(
    workspace: Path,
    doc_type: OfficeDocType,
    document_id: str,
) -> Path:
    """Compose the per-document directory under the workspace sandbox.

    Output: ``<workspace>/office/<doc_type>/<document_id>/``

    Validates ``document_id`` (see :func:`validate_doc_id`) but does
    NOT touch the filesystem — callers that want the directory to
    exist must still call ``.mkdir(parents=True, exist_ok=True)``.

    This helper centralizes the ``office/<docType>/<docId>`` layout
    arithmetic that the storage layer's ``generate_document_dir`` and
    ``document_path`` (and any future persistence helper) need to
    reproduce; centralizing prevents the layout from drifting between
    modules when someone adds an ``office/<extra>`` segment.
    """
    validate_doc_id(document_id)
    return workspace / "office" / doc_type.value / document_id


def managed_document_path(
    workspace: Path,
    doc_type: OfficeDocType,
    document_id: str,
    filename: str,
) -> Path:
    """Compose the per-document path under the workspace sandbox.

    Output: ``<workspace>/office/<doc_type>/<document_id>/<basename>``

    Validates:

    - ``document_id`` against ``_DOC_ID_PATTERN`` (no ``..``, no slashes,
      no shell metacharacters).
    - ``filename`` via :func:`validate_supported_filename` (separator +
      extension + traversal checks).
    - The composed path stays inside ``workspace`` after resolving (extra
      defense-in-depth).

    Returns the resolved Path. **Does not create any directories** —
    callers must still call ``.mkdir(parents=True, exist_ok=True)`` if
    they want the on-disk layout to exist.
    """
    validate_doc_id(document_id)
    safe_filename = validate_supported_filename(filename, doc_type)

    target = (
        managed_document_directory(workspace, doc_type, document_id) / safe_filename
    ).resolve()
    resolved_workspace = workspace.resolve()
    if not is_within(resolved_workspace, target):
        raise OfficePathError(
            f"Resolved managed path escapes workspace: {target!s}",
            file_path=target,
        )
    return target


__all__ = [
    "is_within",
    "resolve_within",
    "validate_doc_id",
    "validate_supported_filename",
    "managed_document_directory",
    "managed_document_path",
]
