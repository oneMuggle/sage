"""Win7 Python bundling dependency contracts."""

from __future__ import annotations

from pathlib import Path

_REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements-py38.txt"


def test_win7_pins_lxml_to_a_python38_windows_wheel() -> None:
    """Avoid resolving lxml source releases without libxml2 headers on Windows."""
    lines = _REQUIREMENTS.read_text(encoding="utf-8").splitlines()

    assert any(line.startswith("lxml==5.4.0") for line in lines), (
        "Win7 requirements must pin lxml==5.4.0 so pip selects the cp38 Windows "
        "wheel instead of compiling lxml from source."
    )
