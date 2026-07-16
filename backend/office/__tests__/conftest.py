"""Pytest fixtures for office module tests.

These fixtures programmatically generate real .pptx/.docx/.xlsx files using
the same libraries we'll be testing. This is "write-then-read" testing —
the generator exercises the library, then the reader is tested against
the generator's output.

Why not commit static .pptx/.docx/.xlsx fixtures?
- Binary diffs are hard to review
- Different python-pptx/python-docx/openpyxl versions may produce slightly
  different binary output
- Programmatic generation makes tests self-documenting
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def fixture_dir(tmp_path: Path) -> Path:
    """Per-test scratch directory. Each test gets a fresh tmp_path."""
    return tmp_path


def make_minimal_png(path: Path) -> Path:
    """Create a 1x1 red PNG for image-embedding tests.

    Using a hand-crafted minimal PNG (67 bytes) avoids any image dependency.
    Format: 1x1, 8-bit grayscale, red channel (actually grayscaled but rendered).
    """
    import base64

    b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwA"
        "FBQH/niTgwAAAABJRU5ErkJggg=="
    )
    path.write_bytes(base64.b64decode(b64))
    return path
