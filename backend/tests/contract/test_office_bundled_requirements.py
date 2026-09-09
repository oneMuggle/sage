"""Office runtime bundled-dependencies contract.

Goal: ensure the Windows NSIS installer bundles every distribution imported
at launch time by ``backend.office`` (PPT/Word/Excel/PDF readers + generators
+ Word template engine).

If any required distribution is omitted from
``backend/requirements-bundled.txt`` but imported at launch time, the
packaged Python 3.11 embeddable will raise ``ModuleNotFoundError`` for
end-users (the Wiki room / Office route layer can never get to a 200 OK
without them). This contract makes that omission a test failure rather
than a release-time regression.

References:
- backend/office/ppt.py           imports python-pptx (``pptx``)
- backend/office/word.py          imports python-docx (``docx``)
- backend/office/excel.py         imports openpyxl    (``openpyxl``)
- backend/office/word_template.py imports docxtpl     (``docxtpl``)
- backend/office/pdf.py           imports pymupdf     (``pymupdf``) at top level
                                  + reportlab lazily in ``_generate_pdf_with_reportlab``
- backend/office/pdf_forms.py     imports pymupdf     (``pymupdf``) at top level
- backend/requirements-bundled.txt feeds scripts/bundle-python-main.ps1
- backend/api/office_routes.py    imports the above via
                                  ``from backend.office.pdf import generate_pdf``
                                  → import chain loads pymupdf at FastAPI startup

Note: reportlab is imported lazily inside ``_generate_pdf_with_reportlab``,
so a missing reportlab would only surface on first PDF generation. We still
bundle it because the bundled installer should not 500 the first time a user
hits the PDF endpoint. Adding it to REQUIRED keeps the contract strict
("bundled deps match launch-time imports AND the documented dep set").
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.version import Version

# Distribution name (PyPI / requirements.txt) -> importable module name.
# These must stay in sync with backend/office/* top-level imports; if a new
# reader module is added there, extend REQUIRED below AND add the
# corresponding line to backend/requirements-bundled.txt.
REQUIRED = {
    "python-pptx": "pptx",
    "python-docx": "docx",
    "openpyxl": "openpyxl",
    # Phase 2 (2026-09-05): Word template + PDF read/form/generate
    "docxtpl": "docxtpl",
    "PyMuPDF": "pymupdf",
    "reportlab": "reportlab",
}

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_BUNDLED_REQ = _BACKEND_DIR / "requirements-bundled.txt"
# Source-of-truth for runtime deps:
#   - main:           backend/requirements.txt      (Python 3.10, pydantic 2.x)
#   - release/win7:   backend/requirements-py38.txt (Python 3.8, pydantic 1.x)
# On win7, ``requirements.txt`` is a leftover from main sync and only carries
# Phase 1 office deps; the actual dev/installed source-of-truth is the
# -py38.txt sibling. Pick whichever exists so the contract holds on both
# branches without losing the cross-file drift check on main.
_PY38_REQ = _BACKEND_DIR / "requirements-py38.txt"
_PARSE_REQ = _PY38_REQ if _PY38_REQ.exists() else _BACKEND_DIR / "requirements.txt"


def _parse_pinned_or_minimum(path: Path) -> dict:
    """Return {distribution: version_spec} for every dep line.

    Accepts both ``distro==X.Y.Z`` (exact pin) and ``distro>=X.Y.Z`` (minimum
    floor). The contract below only requires that ``backend/requirements-bundled.txt``
    declares each required distribution — not that it pins to the same
    operator as ``backend/requirements.txt`` — because some Phase 2 deps
    (docxtpl, PyMuPDF, reportlab) are written with ``>=`` in requirements.txt
    to allow patch upgrades without churning the source-of-truth file.

    Ignores editable installs (``-e ...``), comments, and blank lines.
    """
    result: dict = {}
    pin_re = re.compile(r"^([A-Za-z0-9_.+-]+)\s*(==|>=|<=|~=|!=|>|<)\s*([0-9][A-Za-z0-9_.+!-]*)")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-e "):
            continue
        match = pin_re.match(line)
        if match is None:
            continue
        result[match.group(1)] = f"{match.group(2)}{match.group(3)}"
    return result


def _extract_version(op: str, spec: str) -> str:
    """Strip ``op`` prefix from a spec like ``>=0.20.0`` → ``0.20.0``.

    Asserts that ``spec`` actually starts with ``op`` and that a version
    follows — callers gate on ``spec.startswith(op)`` so the regex always
    matches; the assert is defensive belt-and-suspenders for future
    refactors.
    """
    assert spec.startswith(op), f"spec {spec!r} does not start with {op!r}"
    match = re.match(rf"{re.escape(op)}([0-9][A-Za-z0-9_.+!-]*)", spec)
    assert match is not None, f"malformed spec {spec!r}"
    return match.group(1)


def test_bundled_requirements_include_office_runtime_packages() -> None:
    """Every Office module's distribution is declared in bundled requirements.

    Accepts either ``==`` exact pin or ``>=`` minimum floor — see
    ``_parse_pinned_or_minimum`` for rationale. The contract is "bundled
    deps cover what backend.office imports at launch time", not "bundled
    deps match requirements.txt exactly".
    """
    bundled_versions = _parse_pinned_or_minimum(_BUNDLED_REQ)
    missing = [distribution for distribution in REQUIRED if distribution not in bundled_versions]
    assert not missing, (
        f"{missing} are missing from backend/requirements-bundled.txt; "
        f"the Windows NSIS installer would ship without "
        + " / ".join(f"{d} (`import {REQUIRED[d]}`)" for d in missing)
        + " and the bundled backend would fail to start."
    )


def test_bundled_office_versions_meet_requirements_txt_floor() -> None:
    """Office distributions in ``requirements-bundled.txt`` meet the floor in source-of-truth.

    Compares ``requirements-bundled.txt`` against whichever source-of-truth
    exists (``requirements.txt`` on main, ``requirements-py38.txt`` on
    release/win7) — see ``_PARSE_REQ``.

    Operator combinations accepted:

    - ``==`` req + ``==`` bundled → strict equal
    - ``>=`` req + ``>=`` bundled → floors equal (drift means dev/installer
      disagree on minimum-supported version)
    - ``>=`` req + ``==`` bundled → bundled pin must be at or above the floor
    - ``==`` req + ``>=`` bundled → bundled floor must be at or below the pin
      (this is the main→bundled promotion pattern: dev pins exactly for
      reproducibility, installer widens to a floor so patch upgrades ship
      without churn — e.g. docxtpl==0.20.0 in win7 source-of-truth,
      docxtpl>=0.20.0 in bundled.txt)

    Win7 special case: ``PyMuPDF`` ships with bundled floor ``>=1.25.0``
    (matches main's cp311-only comment) but the win7 source-of-truth is
    pinned to ``==1.24.11`` because that is the last Py3.8 release with
    prebuilt wheels on PyPI. The bundled installer uses Python 3.11, so the
    bundled floor is safe at install time; the dev/source-of-truth just
    cannot match it. The test marks this split as expected and skips the
    operator check rather than failing. Remove the entry once win7 bumps
    PyMuPDF to 1.25+ (which would require dropping Py3.8 support).
    """
    bundled_versions = _parse_pinned_or_minimum(_BUNDLED_REQ)
    requirements_versions = _parse_pinned_or_minimum(_PARSE_REQ)
    is_win7 = _PARSE_REQ.name == "requirements-py38.txt"
    # Distributions whose bundled operator intentionally diverges from the
    # win7 py38 source-of-truth (see docstring).
    win7_floor_drift_allowed = {"PyMuPDF"} if is_win7 else set()

    for distribution in REQUIRED:
        assert distribution in requirements_versions, (
            f"{distribution} is missing from the source-of-truth file "
            f"({_PARSE_REQ.name}); fix the source-of-truth first."
        )
        assert distribution in bundled_versions, (
            f"{distribution} is present in {_PARSE_REQ.name} but missing "
            f"from requirements-bundled.txt."
        )
        if distribution in win7_floor_drift_allowed:
            continue
        req_spec = requirements_versions[distribution]
        bnd_spec = bundled_versions[distribution]
        if req_spec.startswith("==") and bnd_spec.startswith("=="):
            assert bnd_spec == req_spec, (
                f"Version drift for {distribution}: {_PARSE_REQ.name} pins "
                f"{req_spec!r} but requirements-bundled.txt pins {bnd_spec!r}. "
                f"Update both to match."
            )
        elif req_spec.startswith(">=") and bnd_spec.startswith("=="):
            req_floor = Version(_extract_version(">=", req_spec))
            bnd_version = Version(_extract_version("==", bnd_spec))
            assert bnd_version >= req_floor, (
                f"{distribution} bundled as {bnd_spec!r} is below the "
                f"{_PARSE_REQ.name} floor {req_spec!r}."
            )
        elif req_spec.startswith(">=") and bnd_spec.startswith(">="):
            # Both >= floors must be equal — comparing versions for
            # >= operators is non-trivial (PEP 440 allows post-releases,
            # pre-releases, etc.) and our floor strings are simple
            # numeric so equality is safe here.
            assert bnd_spec == req_spec, (
                f"{distribution} floor drift: {_PARSE_REQ.name} has "
                f"{req_spec!r} but requirements-bundled.txt has {bnd_spec!r}."
            )
        elif req_spec.startswith("==") and bnd_spec.startswith(">="):
            # Main→bundled promotion: dev pins exactly, installer widens
            # to a minimum floor. Bundled floor must be at or below the
            # pin (so the pinned version satisfies the floor).
            req_pin = Version(_extract_version("==", req_spec))
            bnd_floor = Version(_extract_version(">=", bnd_spec))
            assert bnd_floor <= req_pin, (
                f"{distribution}: {_PARSE_REQ.name} pins {req_spec!r} but "
                f"requirements-bundled.txt raises the floor to {bnd_spec!r}, "
                f"which would reject the pinned version."
            )
        else:
            raise AssertionError(
                f"unexpected operator combination for {distribution}: "
                f"{_PARSE_REQ.name}={req_spec!r}, bundled={bnd_spec!r}"
            )
