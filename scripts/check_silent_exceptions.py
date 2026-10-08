# ruff: noqa: UP006, UP007, UP035 — Python 3.8 typing compatibility
"""AST ratchet gate for broad silent exception handlers in backend/ (L3).

Flags ``except:``, ``except Exception:``, or ``except BaseException:`` blocks
whose body is solely ``pass`` or ``...`` without logging or re-raising.
Enforces per-subsystem ratchet ceilings from ``scripts/silent-exceptions-baseline.json``.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "scripts" / "silent-exceptions-baseline.json"
BROAD_NAMES = frozenset({"Exception", "BaseException"})


def _is_broad_type(type_node: Optional[ast.expr]) -> bool:
    if type_node is None:
        return True
    if isinstance(type_node, ast.Name):
        return type_node.id in BROAD_NAMES
    if isinstance(type_node, ast.Tuple):
        return any(_is_broad_type(elt) for elt in type_node.elts)
    return False


def _is_silent_body(body: Sequence[ast.stmt]) -> bool:
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    )


def scan_source(source: str, rel_path: str = "<memory>") -> List[Tuple[str, int, str]]:
    """Return list of (rel_path, lineno, handler_label) for broad silent except blocks."""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []
    hits: List[Tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad_type(node.type) and _is_silent_body(node.body):
            label = "bare" if node.type is None else getattr(node.type, "id", "broad")
            hits.append((rel_path, node.lineno, label))
    return sorted(hits, key=lambda item: item[1])


def scan_backend(root: Path = REPO_ROOT) -> Tuple[Dict[str, int], List[Tuple[str, int, str]]]:
    backend_dir = root / "backend"
    counts: Counter = Counter()
    all_hits: List[Tuple[str, int, str]] = []
    for py_file in sorted(backend_dir.rglob("*.py")):
        if "tests" in py_file.parts:
            continue
        rel = py_file.relative_to(root).as_posix()
        src = py_file.read_text(encoding="utf-8", errors="replace")
        file_hits = scan_source(src, rel)
        if file_hits:
            parts = py_file.relative_to(root).parts
            subsystem = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
            counts[subsystem] += len(file_hits)
            all_hits.extend(file_hits)
    return dict(sorted(counts.items())), all_hits


def load_baseline(path: Path = BASELINE_PATH) -> Dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data.get("subsystems", {}).items()}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tighten", action="store_true", help="Tighten baseline ceilings to current counts.")
    args = parser.parse_args(argv)

    counts, hits = scan_backend(REPO_ROOT)
    baseline = load_baseline(BASELINE_PATH)

    if args.tighten:
        updated = {k: counts.get(k, 0) for k in sorted(set(baseline) | set(counts))}
        payload = {
            "description": "Per-subsystem ratchet ceiling for broad silent except-pass blocks in backend/.",
            "subsystems": updated,
        }
        BASELINE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Tightened silent-exceptions baseline ({sum(updated.values())} total across {len(updated)} subsystems).")
        return 0

    regressions: List[str] = []
    for sub, count in sorted(counts.items()):
        ceiling = baseline.get(sub, 0)
        if count > ceiling:
            regressions.append(f"{sub}: {count} > baseline {ceiling}")

    if regressions:
        print("Silent exception ratchet regression detected:", file=sys.stderr)
        for reg in regressions:
            print(f"  {reg}", file=sys.stderr)
        for rel, lineno, label in hits:
            print(f"  {rel}:{lineno} (except {label}: pass)", file=sys.stderr)
        return 1

    print(
        f"Silent exception ratchet OK: {sum(counts.values())} broad except-pass "
        f"(ceiling {sum(baseline.values())})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
