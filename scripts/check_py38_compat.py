#!/usr/bin/env python3
"""Check backend/ + packages/sage-core/ for PEP 604 / PEP 585 syntax in
type annotations. Used as a CI guardrail on main to prevent new Python 3.10+
syntax from leaking into the release/win7 branch (which is locked to 3.8.10).

Why:
- Win7 LTS bundles Python 3.8.10 (last Win7-supporting version).
- PEP 604 (X | Y union): Py3.10+ runtime syntax; Pydantic 1.x evaluates
  annotations via typing.get_type_hints(), so even with `from __future__
  import annotations` the runtime still chokes on Py3.8.
- PEP 585 (list[T] / dict[K, V] built-in generics): Py3.9+ runtime; same
  evaluation issue.

What we check:
- Function/async function signatures: def f(x: list[int]) -> str | None
- Annotated assignments: x: dict[str, int] = {}
- Variable annotations in module/class scope

What we DO NOT check:
- Runtime expressions using `|` operator (e.g., `{"a": 1} | {"b": 2}` is fine on Py3.9+)
- Tests are excluded by default (tests run on 3.10+ on main; tests on win7 must use
  typing.* because backend/tests/ lives on the 3.8 path)
- `from __future__ import annotations` (Py3.8 reads annotations as strings —
  but Pydantic 1.x + typing.get_type_hints() still evaluates at runtime)

Exit codes:
- 0: clean
- 1: violations found (one or more files)

Run:
    python3 scripts/check_py38_compat.py
    python3 scripts/check_py38_compat.py backend/domain/
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Built-in generics from PEP 585 that we reject in annotations on Py3.8.
PEP585_BUILTINS = frozenset({"list", "dict", "tuple", "set", "frozenset", "type"})

# Default paths scanned. Tests are excluded (they run on the main-only Py3.10 path).
DEFAULT_PATHS = ["backend", "packages/sage-core"]

# Files / dirs always skipped.
SKIP_PATH_FRAGMENTS = (
    "tests/",  # tests run on Py3.10+ on main; not in win7 backend/tests on Py3.8
    "scripts/py38_compat_rewrite.py",  # the rewrite tool itself uses PEP 604/585
    "scripts/check_py38_compat.py",  # the check itself
)


class Visitor(ast.NodeVisitor):
    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.violations: list[tuple[int, str]] = []

    def _check_annotation(self, node: ast.AST, label: str) -> None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            self.violations.append(
                (node.lineno, f"{label}: PEP 604 union syntax (use typing.Union / Optional)")
            )
            return
        if isinstance(node, ast.Subscript):
            base = node.value
            base_name = None
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name in PEP585_BUILTINS:
                self.violations.append(
                    (
                        node.lineno,
                        f"{label}: PEP 585 built-in generic (use typing.{base_name.title()})",
                    )
                )

    def _visit_annotations(self, annotations: ast.AST | None, label: str) -> None:
        if annotations is None:
            return
        if isinstance(annotations, ast.Constant) and annotations.value is None:
            return
        self._check_annotation(annotations, label)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            self._visit_annotations(arg.annotation, f"parameter `{arg.arg}`")
        if node.args.vararg:
            self._visit_annotations(node.args.vararg.annotation, "*args")
        if node.args.kwarg:
            self._visit_annotations(node.args.kwarg.annotation, "**kwargs")
        self._visit_annotations(node.returns, "return type")
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._visit_annotations(node.annotation, "annotated assignment")
        self.generic_visit(node)


def check_file(path: Path, root: Path) -> list[tuple[int, str]]:
    rel = str(path.relative_to(root))
    if any(frag in rel for frag in SKIP_PATH_FRAGMENTS):
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError:
        return []
    visitor = Visitor(rel)
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "paths",
        nargs="*",
        default=DEFAULT_PATHS,
        help=f"paths to scan (default: {' '.join(DEFAULT_PATHS)})",
    )
    args = parser.parse_args()

    root = Path.cwd().resolve()
    total_violations = 0
    files_checked = 0
    files_with_violations = 0

    for path_arg in args.paths:
        target = (root / path_arg).resolve()
        if target.is_file():
            files = [target]
        else:
            files = [p for p in target.rglob("*.py") if p.is_file()]
        for f in files:
            files_checked += 1
            violations = check_file(f, root)
            if violations:
                files_with_violations += 1
                print(f"::error file={f.relative_to(root)}")
                for lineno, msg in violations:
                    print(f"{f.relative_to(root)}:{lineno}: {msg}")
                total_violations += len(violations)

    print()
    print(f"Scanned {files_checked} files; {files_with_violations} with violations; {total_violations} total")

    return 1 if total_violations else 0


if __name__ == "__main__":
    sys.exit(main())