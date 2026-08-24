"""Office / text extraction adapter for Wiki ingest (Task 3 step 5+6).

The Wiki ingest pipeline originally only accepted plain text files
(``Path.read_text()``) and crashed on Office binaries. This module is
the bridge that lets DOCX / PPTX / XLSX files flow through the same
ingest path without:

* blocking the chat forever on a multi-GB attachment,
* OOM-ing on a deck with 10k slides,
* or silently swallowing malformed binaries.

Hard limits (exported so downstream tests / observability can rely on
them):

* :data:`MAX_FILE_BYTES` -- single-file size cap. Files larger than this
  are rejected **before** any Office parser opens them. Default: 20 MB.
* :data:`MAX_TEXT_CHARS` -- text byte cap for the returned string.
  Exceeding the cap truncates with an explicit ``truncated`` flag (no
  silent drop of the tail). Default: 200_000 (200 KB).
* :data:`MAX_PARSE_SECONDS` -- wall-clock cap on the Office parser.
  Exceeding it raises :class:`ParseTimeoutError` so the Wiki ingest
  surfaces a structured failure instead of hanging.

Public surface:

* :func:`extract_text_for_ingest` -- the single entry point used by
  :mod:`backend.wiki.ingest`. Dispatches on suffix.
* :class:`FileTooLargeError`, :class:`ParseTimeoutError` -- structured
  failures the caller can downcast.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Limits (public surface — tests + observability depend on these)
# ──────────────────────────────────────────────────────────────────────


MAX_FILE_BYTES: int = 20 * 1024 * 1024  # 20 MB
MAX_TEXT_CHARS: int = 200_000           # 200 KB
MAX_PARSE_SECONDS: float = 10.0


# ──────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────


class FileTooLargeError(Exception):
    """Raised when an input file exceeds ``max_file_bytes``.

    Carries the offending path + observed size so callers can surface a
    user-friendly error (e.g. "file too large for ingest: 45 MB > 20 MB").
    """

    def __init__(self, file_path: Path, size_bytes: int, cap_bytes: int) -> None:
        super().__init__(
            f"file_too_large: {file_path} is {size_bytes} bytes > cap {cap_bytes}"
        )
        self.file_path = file_path
        self.size_bytes = size_bytes
        self.cap_bytes = cap_bytes


class ParseTimeoutError(Exception):
    """Raised when the Office parser exceeds ``max_seconds``."""


# ──────────────────────────────────────────────────────────────────────
# Office-binary → str helpers
# ──────────────────────────────────────────────────────────────────────
# These are split out (instead of inlined into ``extract_text_for_ingest``)
# so tests can monkey-patch a single point and force a slow parse without
# constructing a real, complex DOCX.


def _read_docx_text(file_path: Path) -> str:
    """Flatten a .docx into a single text string.

    Order: title → paragraphs (style is included as a prefix when it
    looks like a heading) → tables (rows joined with ``\\t`` and a
    trailing newline). Empty cells / paragraphs are dropped.
    """
    from backend.office.word import read_docx

    result = read_docx(file_path, workspace_path="")
    chunks = []
    title = result.summary.generated_filename or ""
    if title:
        chunks.append(title)
    for para in result.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if para.level and para.level > 0:
            chunks.append(f"{'#' * para.level} {text}")
        else:
            chunks.append(text)
    for tbl in result.tables:
        for row in tbl.rows:
            line = "\t".join(cell.strip() for cell in row if cell and cell.strip())
            if line:
                chunks.append(line)
    return "\n\n".join(chunks)


def _read_pptx_text(file_path: Path) -> str:
    """Flatten a .pptx into a single text string.

    Per-slide output: ``## {title}\\n{bullets}\\n> {notes}`` (notes
    omitted when empty).
    """
    from backend.office.ppt import read_ppt

    result = read_ppt(file_path, workspace_path="")
    chunks = []
    for slide in result.slides:
        head = f"## {slide.title}" if slide.title else f"## Slide {slide.index + 1}"
        body_parts = []
        if slide.text_blocks:
            body_parts.extend(t.strip() for t in slide.text_blocks if t and t.strip())
        body = "\n".join(f"- {b}" for b in body_parts)
        slide_text = f"{head}\n{body}" if body else head
        if slide.notes and slide.notes.strip():
            slide_text += f"\n> {slide.notes.strip()}"
        chunks.append(slide_text)
    return "\n\n".join(chunks)


def _read_xlsx_text(file_path: Path) -> str:
    """Flatten a .xlsx into a single text string.

    Per-sheet output: ``# Sheet: {name}\\n{rows as tab-joined}``.
    """
    from backend.office.excel import read_xlsx

    result = read_xlsx(file_path, workspace_path="")
    chunks = []
    for sheet in result.sheets:
        head = f"# Sheet: {sheet.name}"
        lines = []
        if sheet.rows:
            for row in sheet.rows:
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append("\t".join(cells))
        sheet_text = head + ("\n" + "\n".join(lines) if lines else "")
        chunks.append(sheet_text)
    return "\n\n".join(chunks)


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────


_OFFICE_READERS = {
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}

_PLAIN_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def _enforce_size(file_path: Path, max_file_bytes: int) -> None:
    """Stat the file and reject oversize inputs *before* opening them.

    This guard exists because python-docx / python-pptx / openpyxl will
    happily load multi-GB zips into memory before we get a chance to
    bail out. ``FileTooLargeError`` short-circuits at the OS stat call.
    """
    size = file_path.stat().st_size
    if size > max_file_bytes:
        raise FileTooLargeError(file_path, size, max_file_bytes)


def _truncate(text: str, max_text_chars: int) -> Tuple[str, bool]:
    """Return ``(text, truncated)`` honoring the byte cap.

    ``max_text_chars == 0`` is a valid edge case (return ``""`` and
    flag ``truncated=True``).
    """
    if max_text_chars is None or max_text_chars < 0:
        return text, False
    if len(text) <= max_text_chars:
        return text, False
    return text[:max_text_chars], True


def _time_limited_call(
    fn,
    args: Tuple,
    kwargs: Dict[str, Any],
    max_seconds: float,
) -> Any:
    """Run ``fn`` in a worker thread and raise :class:`ParseTimeoutError`
    on overrun.

    Implemented via a daemon thread + ``join(timeout=)`` rather than
    signals so it works cross-platform (signals only deliver on the
    main thread). The worker thread is left to die on overrun; it's
    daemonized so the test suite never leaks it.
    """
    if max_seconds is None or max_seconds <= 0:
        # No cap configured (caller passed 0 to disable). Run inline.
        return fn(*args, **kwargs)

    holder: Dict[str, Any] = {}

    def _runner() -> None:
        try:
            holder["result"] = fn(*args, **kwargs)
            holder["error"] = None
        except BaseException as exc:  # noqa: BLE001 -- propagate to caller
            holder["error"] = exc

    th = threading.Thread(target=_runner, daemon=True)
    start = time.monotonic()
    th.start()
    th.join(timeout=max_seconds)
    elapsed = time.monotonic() - start
    if th.is_alive():
        # NB: we can't kill the thread, but daemon=True ensures it
        # doesn't block process exit.
        raise ParseTimeoutError(
            f"parse exceeded {max_seconds:.2f}s (elapsed={elapsed:.2f}s)"
        )
    if holder.get("error") is not None:
        raise holder["error"]
    return holder.get("result")


def extract_text_for_ingest(
    file_path: Path,
    *,
    max_file_bytes: Optional[int] = None,
    max_text_chars: Optional[int] = None,
    max_seconds: Optional[float] = None,
    return_meta: bool = False,
):
    """Extract bounded text from a file the Wiki ingest pipeline accepts.

    Dispatches on suffix:

    * ``.md`` / ``.markdown`` / ``.txt`` — pass through ``read_text``.
    * ``.docx`` / ``.pptx`` / ``.xlsx`` — use the existing office
      readers to flatten the document.
    * anything else — raise :class:`ValueError`.

    Args:
        file_path: Input file (must exist).
        max_file_bytes: Override :data:`MAX_FILE_BYTES` for this call.
        max_text_chars: Override :data:`MAX_TEXT_CHARS` for this call.
            When omitted, no truncation is applied (caller is expected
            to slice). When provided, the returned text never exceeds
            the cap and a ``truncated`` flag is set.
        max_seconds: Override :data:`MAX_PARSE_SECONDS` for this call.
            When omitted, no timeout is enforced (Office readers are
            fast for normal sizes — callers only need a cap for the
            huge-attachment DoS case).
        return_meta: When ``True``, return ``(text, meta_dict)`` instead
            of bare ``text``. ``meta_dict`` carries ``doc_type``,
            ``truncated``, and ``bytes_size`` for observability.

    Returns:
        ``str`` (default) or ``(str, dict)`` when ``return_meta=True``.

    Raises:
        FileNotFoundError: file does not exist.
        FileTooLargeError: ``size > max_file_bytes``.
        ParseTimeoutError: parser ran longer than ``max_seconds``.
        ValueError: unsupported suffix.
        OfficeParseError: malformed Office binary (re-raised from the
            underlying reader; the Wiki ingest path treats this as a
            structured ingest failure).
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    cap_bytes = max_file_bytes if max_file_bytes is not None else MAX_FILE_BYTES
    _enforce_size(file_path, cap_bytes)

    suffix = file_path.suffix.lower()

    meta: Dict[str, Any] = {
        "doc_type": None,
        "truncated": False,
        "bytes_size": file_path.stat().st_size,
    }

    if suffix in _PLAIN_TEXT_SUFFIXES:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        meta["doc_type"] = "text"
    elif suffix in _OFFICE_READERS:
        doc_type = _OFFICE_READERS[suffix]
        meta["doc_type"] = doc_type
        # NB: resolve the reader via ``getattr`` at call time so tests can
        # ``monkeypatch.setattr(ext, "_read_docx_text", slow_fn)`` and have
        # the timeout path exercised without constructing a real DOCX.
        reader = getattr(sys.modules[__name__], f"_read_{doc_type}_text")
        cap_seconds = max_seconds if max_seconds is not None else MAX_PARSE_SECONDS
        text = _time_limited_call(reader, (file_path,), {}, cap_seconds)
    else:
        raise ValueError(
            f"unsupported_suffix: {suffix!r} not handled by "
            f"extract_text_for_ingest"
        )

    if max_text_chars is not None:
        text, meta["truncated"] = _truncate(text, max_text_chars)

    if return_meta:
        return text, meta
    return text


__all__ = [
    "MAX_FILE_BYTES",
    "MAX_TEXT_CHARS",
    "MAX_PARSE_SECONDS",
    "FileTooLargeError",
    "ParseTimeoutError",
    "extract_text_for_ingest",
]