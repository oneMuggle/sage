"""Local OCR bundled-dependencies contract.

The packaged main installer must include the OCR engine, otherwise the
feature is visible in the UI but always reports "unavailable" for end users.
This contract keeps ``backend/requirements-bundled.txt`` in sync with the
OCR runtime imports.

Dev/CI stays light: these packages are intentionally absent from
``backend/requirements.txt`` and documented in
``backend/requirements-optional.txt`` instead.
"""

from __future__ import annotations

import re
from pathlib import Path

# Distribution name (PyPI) -> importable module name.
REQUIRED = {
    "rapidocr": "rapidocr",
    "onnxruntime": "onnxruntime",
    "opencv-python-headless": "cv2",
    "Pillow": "PIL",
}

# Path is relative to backend/ where pytest is invoked.
_BUNDLED_REQ = Path(__file__).resolve().parents[2] / "requirements-bundled.txt"
_PIN_RE = re.compile(
    r"^([A-Za-z0-9_.+-]+)\s*((?:==|>=|<=|~=|!=|>|<)[^#\s]+)"
)


def _parse_requirements(path: Path) -> dict:
    result = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-e "):
            continue
        match = _PIN_RE.match(line)
        if match is not None:
            result[match.group(1).lower()] = match.group(2)
    return result


def test_bundled_requirements_include_ocr_runtime_packages() -> None:
    bundled = _parse_requirements(_BUNDLED_REQ)

    missing = [name for name in REQUIRED if name.lower() not in bundled]
    assert not missing, (
        f"{missing} are missing from backend/requirements-bundled.txt; "
        "the packaged installer would report local OCR as unavailable"
    )


def test_bundled_numpy_stays_below_2_for_opencv_compat() -> None:
    bundled = _parse_requirements(_BUNDLED_REQ)

    assert bundled.get("numpy") == ">=1.24,<2", (
        "bundled numpy must stay on 1.x so pip resolves "
        "opencv-python-headless 4.11.x (4.12+ requires numpy>=2)"
    )
