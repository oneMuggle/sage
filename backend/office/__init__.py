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
