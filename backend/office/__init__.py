"""Office document features (PPT/Word/Excel read + generate).

Module map:
- models.py  — Pydantic request/response models
- errors.py  — exception hierarchy
- ppt.py     — PPTX reader + generator (python-pptx)
- word.py    — DOCX reader + generator (python-docx)
- excel.py   — XLSX reader + generator (openpyxl + pandas)
- storage.py — workspace path validation + SQLite persistence

See docs/plans/2026-07-16_office-features.md for design.
"""

# Phase 2 exports are loaded on demand so stdlib-only path checks can import
# ``backend.office.path_safety`` without installing binary Office readers.
_PHASE_2_EXPORTS = {
    "analyze_word_template": (".word_template", "analyze_word_template"),
    "fill_word_template": (".word_template", "fill_word_template"),
    "generate_pdf": (".pdf", "generate_pdf"),
    "read_pdf": (".pdf", "read_pdf"),
    "fill_pdf_form": (".pdf_forms", "fill_pdf_form"),
    "read_pdf_form": (".pdf_forms", "read_pdf_form"),
}

__all__ = list(_PHASE_2_EXPORTS)


def __getattr__(name):
    """Load optional Phase 2 exports only when they are requested."""
    try:
        module_name, attribute_name = _PHASE_2_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    from importlib import import_module

    attribute = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = attribute
    return attribute
