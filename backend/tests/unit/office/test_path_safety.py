"""Unit tests for backend.office.path_safety.

Covers both POSIX and Windows flavor checks. The helper primitives must
work on PurePosixPath/PureWindowsPath so the workspace-containment guards
stay correct on whatever OS the project runs on.

Per plan §6 R1: workspace traversal (../), absolute paths outside the
workspace, sibling-prefix collisions (e.g. ``/tmp/work`` vs
``/tmp/work-evil``), and symlink escapes must all raise OfficePathError.
``relative_to`` raises ValueError for non-children, which is exactly the
hook we need — never fall back to string-prefix checks.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from backend.office.errors import OfficePathError
from backend.office.models import OfficeDocType
from backend.office.path_safety import (
    is_within,
    managed_document_path,
    resolve_within,
    validate_supported_filename,
)

# ──────────────────────────────────────────────────────────────────────
# is_within — flavor-agnostic containment primitive
# ──────────────────────────────────────────────────────────────────────


def test_is_within_rejects_sibling_prefix() -> None:
    """Sibling-prefix attack: ``/tmp/work-evil`` must NOT be inside ``/tmp/work``.

    This is the canonical string-prefix bug the refactor fixes.
    """
    assert is_within(PurePosixPath("/tmp/work"), PurePosixPath("/tmp/work-evil")) is False


def test_is_within_accepts_nested_child() -> None:
    base = PurePosixPath("/tmp/work")
    child = PurePosixPath("/tmp/work/office/word/abc/file.docx")
    assert is_within(base, child) is True


def test_is_within_rejects_parent_directory() -> None:
    """``..`` segments collapse to parent and must fail containment."""
    base = PurePosixPath("/tmp/work")
    parent = PurePosixPath("/tmp")
    assert is_within(base, parent) is False


def test_is_within_rejects_unrelated_absolute_path() -> None:
    base = PurePosixPath("/tmp/work")
    other = PurePosixPath("/etc/passwd")
    assert is_within(base, other) is False


def test_is_within_handles_windows_separators() -> None:
    """PureWindowsPath must match with backslash separators, not POSIX slash."""
    assert (
        is_within(
            PureWindowsPath(r"C:\work"),
            PureWindowsPath(r"C:\work\office\word\id\file.docx"),
        )
        is True
    )


def test_is_within_rejects_windows_sibling_prefix() -> None:
    """Windows sibling-prefix attack: ``C:\\work-evil`` must NOT be inside ``C:\\work``."""
    assert (
        is_within(
            PureWindowsPath(r"C:\work"),
            PureWindowsPath(r"C:\work-evil\file.docx"),
        )
        is False
    )


def test_is_within_handles_backslash_in_posix() -> None:
    """PurePosixPath treats backslash as a regular filename char — that's OK,
    the path can still nest under base if the name component matches."""
    assert is_within(PurePosixPath("/tmp/work"), PurePosixPath("/tmp/work/weird\\name")) is True
    assert is_within(PurePosixPath("/tmp/work"), PurePosixPath("/tmp/other\\name")) is False


def test_is_within_rejects_different_drives_on_windows() -> None:
    """PureWindowsPath: D:\\ must not be inside C:\\."""
    assert (
        is_within(
            PureWindowsPath(r"C:\work"),
            PureWindowsPath(r"D:\work\file.docx"),
        )
        is False
    )


# ──────────────────────────────────────────────────────────────────────
# resolve_within — concretizes and verifies
# ──────────────────────────────────────────────────────────────────────


def test_resolve_within_resolves_and_accepts_valid_path(tmp_path: Path) -> None:
    nested = tmp_path / "office" / "word" / "abc"
    nested.mkdir(parents=True)
    target = nested / "file.docx"
    target.write_text("hello")
    result = resolve_within(tmp_path, target)
    assert result.is_file()
    assert result.name == "file.docx"


def test_resolve_within_rejects_traversal(tmp_path: Path) -> None:
    """Paths that resolve outside the workspace must raise OfficePathError."""
    outside = tmp_path.parent / "evil"
    with pytest.raises(OfficePathError):
        resolve_within(tmp_path, outside)


def test_resolve_within_rejects_sibling_prefix_real(tmp_path: Path) -> None:
    """On real FS: ``<tmp>/work-evil`` is NOT inside ``<tmp>/work``."""
    real_path = tmp_path.resolve()
    sibling = real_path.parent / (real_path.name + "-evil")
    with pytest.raises(OfficePathError):
        resolve_within(real_path, sibling)


def test_resolve_within_rejects_symlink_escape(tmp_path: Path) -> None:
    """If a directory contains a symlink pointing outside, resolve_within must reject it."""
    outside_dir = tmp_path.parent
    if not outside_dir.exists() or outside_dir == tmp_path:
        pytest.skip("tmp_path has no resolvable parent for symlink escape test")
    link_dir = tmp_path / "link"
    try:
        link_dir.symlink_to(outside_dir)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem does not support symlinks")
    target = link_dir / "evil.txt"
    with pytest.raises(OfficePathError):
        resolve_within(tmp_path, target)


# ──────────────────────────────────────────────────────────────────────
# managed_document_path — composes all guards
# ──────────────────────────────────────────────────────────────────────


def test_managed_document_path_rejects_cross_type_extension(tmp_path: Path) -> None:
    """Word doc with ``.xlsx`` extension must raise (extension must match doc type)."""
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.WORD, "abc123", "file.xlsx")


def test_managed_document_path_rejects_ppt_with_docx_extension(tmp_path: Path) -> None:
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.PPT, "abc123", "file.docx")


def test_managed_document_path_rejects_excel_with_pptx_extension(tmp_path: Path) -> None:
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.EXCEL, "abc123", "file.pptx")


def test_managed_document_path_rejects_invalid_doc_id(tmp_path: Path) -> None:
    """doc_id must match ``^[a-zA-Z0-9_-]{1,64}$``. Slashes etc. are rejected."""
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.WORD, "../evil", "file.docx")
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.WORD, "id with spaces", "file.docx")
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.WORD, "id/with/slashes", "file.docx")


def test_managed_document_path_rejects_filename_with_separator(tmp_path: Path) -> None:
    """Filenames containing path separators must be rejected."""
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.WORD, "abc123", "subdir/file.docx")
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.WORD, "abc123", "..\\file.docx")


def test_managed_document_path_rejects_parent_traversal_in_filename(tmp_path: Path) -> None:
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.WORD, "abc123", "..")


def test_managed_document_path_produces_correct_path_under_workspace(tmp_path: Path) -> None:
    """Valid inputs must produce ``<workspace>/office/<doc_type>/<doc_id>/<name>.<ext>``."""
    for doc_type, ext in (
        (OfficeDocType.WORD, "docx"),
        (OfficeDocType.PPT, "pptx"),
        (OfficeDocType.EXCEL, "xlsx"),
    ):
        result = managed_document_path(tmp_path, doc_type, "abc123", f"file.{ext}")
        expected = (tmp_path / "office" / doc_type.value / "abc123" / f"file.{ext}").resolve()
        assert result == expected, f"doc_type={doc_type} mismatch"


def test_managed_document_path_appends_missing_extension(tmp_path: Path) -> None:
    """Missing extension is auto-appended for convenience (matches current behavior)."""
    result = managed_document_path(tmp_path, OfficeDocType.WORD, "abc123", "file")
    assert result.name == "file.docx"


# ──────────────────────────────────────────────────────────────────────
# validate_supported_filename — pure-string filename check
# ──────────────────────────────────────────────────────────────────────


def test_validate_supported_filename_rejects_separators() -> None:
    with pytest.raises(OfficePathError):
        validate_supported_filename("sub/file.docx", OfficeDocType.WORD)
    with pytest.raises(OfficePathError):
        validate_supported_filename("sub\\file.docx", OfficeDocType.WORD)


def test_validate_supported_filename_rejects_parent_traversal() -> None:
    with pytest.raises(OfficePathError):
        validate_supported_filename("..", OfficeDocType.WORD)
    with pytest.raises(OfficePathError):
        validate_supported_filename("../file.docx", OfficeDocType.WORD)


def test_validate_supported_filename_rejects_cross_type_extension() -> None:
    with pytest.raises(OfficePathError):
        validate_supported_filename("file.xlsx", OfficeDocType.WORD)


def test_validate_supported_filename_accepts_valid_name_and_appends_missing_ext() -> None:
    assert validate_supported_filename("file.docx", OfficeDocType.WORD) == "file.docx"
    assert validate_supported_filename("file", OfficeDocType.WORD) == "file.docx"
    assert validate_supported_filename("report.pptx", OfficeDocType.PPT) == "report.pptx"
    assert validate_supported_filename("sheet.xlsx", OfficeDocType.EXCEL) == "sheet.xlsx"
