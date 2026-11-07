# ruff: noqa: UP006, UP007, UP035
"""Unit and repository-wide contract tests for scripts/check_py38_compat.py (L4)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_py38_compat.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location("check_py38_compat", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_py38_compat"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_detects_missing_future_annotations() -> None:
    gate = _load_gate_module()
    bad_src = "def f(x: int | None) -> list[str]:\n    return []\n"
    issues = gate.check_source(bad_src, filename="sample_no_future.py")
    assert len(issues) == 2
    assert all("missing `from __future__ import annotations`" in i for i in issues)


def test_allows_future_annotations_for_regular_functions() -> None:
    gate = _load_gate_module()
    ok_src = (
        "from __future__ import annotations\n\n"
        "def f(x: int | None) -> list[str]:\n"
        "    return []\n"
    )
    assert gate.check_source(ok_src, filename="sample_ok.py") == []


def test_detects_runtime_isinstance_union() -> None:
    gate = _load_gate_module()
    bad_src = (
        "from __future__ import annotations\n\n"
        "def f(x: object) -> bool:\n"
        "    return isinstance(x, int | str)\n"
    )
    issues = gate.check_source(bad_src, filename="sample_isinstance.py")
    assert len(issues) == 1
    assert "isinstance() uses PEP 604 `|` union at runtime" in issues[0]


def test_detects_pydantic_and_fastapi_runtime_annotations() -> None:
    gate = _load_gate_module()
    bad_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class ItemRequest(BaseModel):\n"
        "    tags: list[str]\n\n"
        "@router.post('/items')\n"
        "def create_item(q: str | None = None) -> dict[str, int]:\n"
        "    return {}\n"
    )
    issues = gate.check_source(bad_src, filename="sample_api.py")
    assert len(issues) == 3
    assert any("Pydantic model `ItemRequest`" in i for i in issues)
    assert any("FastAPI route `create_item` param `q`" in i for i in issues)
    assert any("FastAPI route `create_item` return annotation" in i for i in issues)


def test_repository_passes_py38_compat_gate() -> None:
    gate = _load_gate_module()
    targets = [REPO_ROOT / "backend", REPO_ROOT / "packages" / "sage-core"]
    violations = gate.check_paths(targets)
    assert violations == [], "Python 3.8 compatibility violations:\n" + "\n".join(violations)
