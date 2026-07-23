"""Office runtime bundled-dependencies contract.

Goal: ensure the Windows NSIS installer bundles every pure-Python Office
runtime distribution imported by ``backend.office`` (PPT/Word/Excel
readers + generators).

If any of these three distributions is omitted from
``backend/requirements-bundled.txt`` but imported at launch time, the
packaged Python 3.11 embeddable will raise ``ModuleNotFoundError`` for
end-users (the Wiki room / Office route layer can never get to a 200 OK
without them). This contract makes that omission a test failure rather
than a release-time regression.

References:
- backend/office/ppt.py     imports python-pptx (``pptx``)
- backend/office/word.py    imports python-docx (``docx``)
- backend/office/excel.py   imports openpyxl    (``openpyxl``)
- backend/requirements-bundled.txt feeds scripts/bundle-python-main.ps1
"""

from __future__ import annotations

import re
from pathlib import Path

# Distribution name (PyPI / requirements.txt) -> importable module name.
# These must stay in sync with backend/office/{ppt,word,excel}.py
# top-level imports; if a new reader module is added there, extend
# REQUIRED below AND add the corresponding line to
# backend/requirements-bundled.txt.
REQUIRED = {
    "python-pptx": "pptx",
    "python-docx": "docx",
    "openpyxl": "openpyxl",
}

# Path is relative to backend/ where pytest is invoked. pytest.ini sets
# testpaths=tests so this resolves under backend/tests/contract/..
_BUNDLED_REQ = Path(__file__).resolve().parents[2] / "requirements-bundled.txt"
_PARSE_REQ = Path(__file__).resolve().parents[2] / "requirements.txt"


def _pinned_versions(path: Path) -> dict:
    """Return {distribution: version} for every pinned ``distro==X.Y.Z`` line.

    Ignores editable installs (``-e ...``), comments, and blank lines.
    Distributions pinned with ``>=`` or other comparison operators are
    NOT collected — the contract below demands exact version parity with
    ``backend/requirements.txt``, so non-pinned entries fail loudly.
    """
    result: dict = {}
    pin_re = re.compile(r"^([A-Za-z0-9_.+-]+)\s*==\s*([0-9][A-Za-z0-9_.+!-]*)")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-e "):
            continue
        match = pin_re.match(line)
        if match is None:
            continue
        result[match.group(1)] = match.group(2)
    return result


def test_bundled_requirements_include_office_runtime_packages() -> None:
    """Every Office reader module's distribution is pinned in bundled requirements."""
    text = _BUNDLED_REQ.read_text(encoding="utf-8")
    lines = text.splitlines()
    for distribution in REQUIRED:
        assert any(
            line.startswith(distribution + "==") for line in lines
        ), (
            f"{distribution} is missing from backend/requirements-bundled.txt; "
            f"the Windows NSIS installer would ship without it and "
            f"`import {REQUIRED[distribution]}` would fail at startup."
        )


def test_bundled_office_versions_match_requirements_txt() -> None:
    """Office distributions share the exact pinned version with ``requirements.txt``.

    Drift between the two files causes dev environments and packaged
    installs to disagree on which Office runtime was exercised — this
    contract catches drift before release.
    """
    bundled_versions = _pinned_versions(_BUNDLED_REQ)
    requirements_versions = _pinned_versions(_PARSE_REQ)

    for distribution in REQUIRED:
        assert distribution in requirements_versions, (
            f"{distribution} is missing from backend/requirements.txt; "
            f"fix the source-of-truth first."
        )
        assert distribution in bundled_versions, (
            f"{distribution} is present in requirements.txt but missing "
            f"from requirements-bundled.txt."
        )
        assert (
            bundled_versions[distribution] == requirements_versions[distribution]
        ), (
            f"Version drift for {distribution}: "
            f"requirements.txt has {requirements_versions[distribution]!r} "
            f"but requirements-bundled.txt has {bundled_versions[distribution]!r}. "
            f"Update both to match."
        )