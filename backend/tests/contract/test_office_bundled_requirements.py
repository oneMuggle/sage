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
    "pandas": "pandas",
    # Phase 2 (2026-09-05): Word template + PDF read/form/generate
    "docxtpl": "docxtpl",
    "PyMuPDF": "pymupdf",
    "reportlab": "reportlab",
}

# Path is relative to backend/ where pytest is invoked. pytest.ini sets
# testpaths=tests so this resolves under backend/tests/contract/..
_BUNDLED_REQ = Path(__file__).resolve().parents[2] / "requirements-bundled.txt"
_PARSE_REQ = Path(__file__).resolve().parents[2] / "requirements.txt"


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
    """Office distributions in ``requirements-bundled.txt`` meet the floor in ``requirements.txt``.

    For ``==`` pins, the bundled version must equal requirements.txt.
    For ``>=`` floors in requirements.txt, the bundled version (if also
    pinned with ``==``) must be at or above the floor. When both files
    use ``>=``, we only check that both declare the same minimum floor —
    drift between the floor strings would mean dev vs. installer disagree
    on the minimum-supported version.
    """
    bundled_versions = _parse_pinned_or_minimum(_BUNDLED_REQ)
    requirements_versions = _parse_pinned_or_minimum(_PARSE_REQ)

    for distribution in REQUIRED:
        assert distribution in requirements_versions, (
            f"{distribution} is missing from backend/requirements.txt; "
            f"fix the source-of-truth first."
        )
        assert distribution in bundled_versions, (
            f"{distribution} is present in requirements.txt but missing "
            f"from requirements-bundled.txt."
        )
        req_spec = requirements_versions[distribution]
        bnd_spec = bundled_versions[distribution]
        # If requirements.txt uses ==, bundled must match exactly.
        # If requirements.txt uses >=, bundled must declare >= with same or
        # higher floor (compared via PEP 440 packaging.version.Version).
        if req_spec.startswith("=="):
            assert bnd_spec == req_spec, (
                f"Version drift for {distribution}: requirements.txt pins "
                f"{req_spec!r} but requirements-bundled.txt declares {bnd_spec!r}. "
                f"Update both to match."
            )
        elif req_spec.startswith(">="):
            req_floor = Version(_extract_version(">=", req_spec))
            if bnd_spec.startswith("=="):
                bnd_version = Version(_extract_version("==", bnd_spec))
                assert bnd_version >= req_floor, (
                    f"{distribution} bundled as {bnd_spec!r} is below the "
                    f"requirements.txt floor {req_spec!r}."
                )
            else:
                # Both >= floors must be equal — comparing versions for
                # >= operators is non-trivial (PEP 440 allows post-releases,
                # pre-releases, etc.) and our floor strings are simple
                # numeric so equality is safe here.
                assert bnd_spec == req_spec, (
                    f"{distribution} floor drift: requirements.txt has "
                    f"{req_spec!r} but requirements-bundled.txt has {bnd_spec!r}."
                )
