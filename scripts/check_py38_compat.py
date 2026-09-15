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

Runtime-API guardrail (regex, ALL files incl. tests — release/win7 CI runs
backend/tests on Py3.8): str.removesuffix/removeprefix, Path.is_relative_to,
datetime.UTC, isinstance(x, A | B), write_text(newline=), zip(strict=),
`except TimeoutError` around asyncio.wait_for, parenthesized multi-item `with (`.
Mark a deliberately guarded call site with the comment `py38: guarded`.

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
import re
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


# ---------------------------------------------------------------------------
# Runtime-API guardrail (regex, applies to tests too — backend/tests runs on
# Py3.8 in the release/win7 CI job). These are *not* annotation issues: they
# blow up at runtime / import time on Py3.8 even though ast.parse succeeds on
# 3.11. Lines carrying the marker ``py38: guarded`` are skipped (used where the
# call sits inside a ``try/except AttributeError`` fallback).
# ---------------------------------------------------------------------------
PY38_GUARD_MARKER = "py38: guarded"
RUNTIME_API_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\.removesuffix\("), "str.removesuffix is Py3.9+ (use endswith + slice)"),
    (re.compile(r"\.removeprefix\("), "str.removeprefix is Py3.9+ (use startswith + slice)"),
    (re.compile(r"\.is_relative_to\("), "Path.is_relative_to is Py3.9+ (use backend.office.path_safety.is_within)"),
    (re.compile(r"\.hardlink_to\("), "Path.hardlink_to is Py3.10+ (use os.link(src, dst))"),
    (re.compile(r"\.with_stem\("), "Path.with_stem is Py3.9+"),
    (re.compile(r"(?<![\w.])(?!os\.)[A-Za-z_]\w*\.readlink\(\)"), "Path.readlink is Py3.9+ (use os.readlink)"),
    (re.compile(r"from datetime import[^\n]*\bUTC\b|\bdatetime\.UTC\b"), "datetime.UTC is Py3.11+ (use timezone.utc)"),
    (re.compile(r"isinstance\([^()]*\b[\w.]+\s*\|\s*[\w.]+"), "PEP 604 union inside isinstance() is Py3.10+ (use a tuple)"),
    (re.compile(r"write_text\([^)]*\bnewline=", re.S), "Path.write_text(newline=) is Py3.10+ (use path.open(newline=''))"),
    (re.compile(r"\bzip\([^)]*\bstrict=", re.S), "zip(strict=) is Py3.10+"),
    # Path.stat(follow_symlinks=) is 3.10+; os.stat / DirEntry.stat accept it on 3.8.
    (re.compile(r"(?<![\w.])(?!os\.)(?!\w*entry\w*\.)[A-Za-z_]\w*\.stat\([^)]*follow_symlinks="), "Path.stat(follow_symlinks=) is Py3.10+ (use os.lstat / os.stat(follow_symlinks=))"),
]
# `except TimeoutError` only matters when the module awaits asyncio.wait_for /
# asyncio.timeout — on Py3.8/3.10 asyncio.TimeoutError is NOT the builtin.
ASYNCIO_TIMEOUT_EXCEPT = re.compile(r"^\s*except\s+TimeoutError\s*(as\s+\w+\s*)?:")
PAREN_WITH_OPEN = re.compile(r"^\s*(async\s+)?with\s*\(\s*(#.*)?$")
PAREN_WITH_CLOSE = re.compile(r"^\s*\)\s*:")
RUNTIME_SKIP_FRAGMENTS = (
    "scripts/py38_compat_rewrite.py",
    "scripts/check_py38_compat.py",
    "compat/win7/asyncio_compat.py",
)


def check_runtime_apis(path: Path, root: Path) -> list[tuple[int, str]]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    if any(frag in rel for frag in RUNTIME_SKIP_FRAGMENTS):
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = source.splitlines()
    uses_asyncio_wait = "asyncio.wait_for(" in source or "asyncio.timeout(" in source
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        lineno = i + 1
        if PY38_GUARD_MARKER in line:
            i += 1
            continue
        # Drop trailing comments so `# noqa: UP017 — datetime.UTC is 3.11+` notes don't trip the regexes.
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        # Multi-line calls: `write_text(\n ..., newline="",\n)` — extend the window to the
        # closing paren (max 12 lines) for the call-kwarg patterns.
        window = code
        if "(" in code and ")" not in code.split("(", 1)[1]:
            k = i + 1
            while k < len(lines) and k <= i + 12:
                window += "\n" + lines[k].split("#", 1)[0]
                if ")" in lines[k]:
                    break
                k += 1
        for pat, msg in RUNTIME_API_PATTERNS:
            if pat.search(window if pat.flags & re.S else code):
                out.append((lineno, f"py38 runtime: {msg}"))
        if uses_asyncio_wait and ASYNCIO_TIMEOUT_EXCEPT.match(code):
            out.append((lineno, "py38 runtime: `except TimeoutError` does not catch asyncio.wait_for timeout on Py3.8/3.10 (use `except (TimeoutError, asyncio.TimeoutError)`)"))
        if PAREN_WITH_OPEN.match(code):
            # Parenthesized multi-item context manager (PEP 617) → SyntaxError on 3.8.
            j = i + 1
            multi = False
            while j < len(lines) and not PAREN_WITH_CLOSE.match(lines[j]):
                body = lines[j].split("#", 1)[0].rstrip()
                if body.endswith(",") or " as " in body:
                    multi = True
                j += 1
            if multi:
                out.append((lineno, "py38 runtime: parenthesized `with (a as x, b as y):` is Py3.9+ grammar (SyntaxError on 3.8; run scripts/py38_compat_rewrite.py)"))
        i += 1
    return out


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
            violations = check_file(f, root) + check_runtime_apis(f, root)
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