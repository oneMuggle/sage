#!/usr/bin/env python3
# ruff: noqa: UP006, UP007, UP035
"""Zero-dependency AST gate for Python 3.8 runtime & import-time compatibility (L4).

Checks ``backend/`` and ``packages/sage-core/`` for four classes of Python 3.9+/3.10+
syntax that break the ``release/win7`` Python 3.8 runtime:

1. Missing ``from __future__ import annotations`` in a module that uses PEP 604
   (``X | Y``) or PEP 585 (``list[int]``, ``dict[str, Any]``, etc.) in annotations
   (raises ``TypeError`` at module import time on Python 3.8).
2. Runtime ``isinstance(x, A | B)`` or ``issubclass(cls, A | B)`` calls (raises
   ``TypeError`` at call time on Python 3.8 even when ``__future__.annotations``
   is active).
3. Pydantic ``BaseModel`` / schema class field annotations using PEP 604 or PEP 585
   (evaluated eagerly via ``typing.get_type_hints()`` on Python 3.8).
4. FastAPI route handler parameter or return annotations using PEP 604 or PEP 585
   (evaluated eagerly at route registration time via ``typing.get_type_hints()``
   on Python 3.8).
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Union

PEP585_BUILTINS = frozenset({"list", "dict", "tuple", "set", "frozenset", "type"})
ROUTE_METHODS = frozenset({"get", "post", "put", "delete", "patch", "websocket", "api_route"})
MODEL_SUFFIXES = ("Model", "Schema", "Request", "Response")


def find_annotation_violations(node: ast.AST) -> List[str]:
    """Return human-readable PEP 604 / PEP 585 violations inside an annotation AST."""
    issues: List[str] = []
    for sub in ast.walk(node):
        lineno = getattr(sub, "lineno", "?")
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
            issues.append(f"line {lineno}: PEP 604 `|` union in annotation")
        elif (
            isinstance(sub, ast.Subscript)
            and isinstance(sub.value, ast.Name)
            and sub.value.id in PEP585_BUILTINS
        ):
            issues.append(
                f"line {lineno}: PEP 585 `{sub.value.id}[...]` generic in annotation"
            )
    return issues


def _has_future_annotations(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(alias.name == "annotations" for alias in node.names):
                return True
    return False


def _is_pydantic_model_class(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and any(s in base.id for s in MODEL_SUFFIXES):
            return True
        if isinstance(base, ast.Attribute) and any(s in base.attr for s in MODEL_SUFFIXES):
            return True
    return False


def _is_fastapi_route_func(fn: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    for dec in fn.decorator_list:
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in ROUTE_METHODS
        ):
            return True
    return False


def _iter_func_args(fn: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> List[ast.arg]:
    args = list(fn.args.posonlyargs) + list(fn.args.args) + list(fn.args.kwonlyargs)
    if fn.args.vararg is not None:
        args.append(fn.args.vararg)
    if fn.args.kwarg is not None:
        args.append(fn.args.kwarg)
    return args


def check_source(source: str, filename: str = "<string>") -> List[str]:
    """Check a single Python source string for Python 3.8 compatibility violations."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"{filename}:{exc.lineno or '?'}: syntax error: {exc.msg}"]

    has_future = _has_future_annotations(tree)
    problems: List[str] = []

    for node in ast.walk(tree):
        # Rule 2: runtime isinstance / issubclass with PEP 604 union
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("isinstance", "issubclass")
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.BinOp)
            and isinstance(node.args[1].op, ast.BitOr)
        ):
            problems.append(
                f"{filename}:{node.lineno}: {node.func.id}() uses PEP 604 `|` union at runtime"
            )

        # Rule 3: Pydantic BaseModel field annotations evaluated at runtime
        if isinstance(node, ast.ClassDef) and _is_pydantic_model_class(node):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and stmt.annotation is not None:
                    for issue in find_annotation_violations(stmt.annotation):
                        problems.append(
                            f"{filename}:{issue} in Pydantic model `{node.name}`"
                        )

        # Rule 4: FastAPI route annotations evaluated at runtime
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fastapi_route_func(node):
            for arg in _iter_func_args(node):
                if arg.annotation is not None:
                    for issue in find_annotation_violations(arg.annotation):
                        problems.append(
                            f"{filename}:{issue} in FastAPI route `{node.name}` param `{arg.arg}`"
                        )
            if node.returns is not None:
                for issue in find_annotation_violations(node.returns):
                    problems.append(
                        f"{filename}:{issue} in FastAPI route `{node.name}` return annotation"
                    )

        # Rule 1: Any PEP 604 / 585 annotation when __future__.annotations is absent
        if not has_future:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in _iter_func_args(node):
                    if arg.annotation is not None:
                        for issue in find_annotation_violations(arg.annotation):
                            problems.append(
                                f"{filename}:{issue} (missing `from __future__ import annotations`)"
                            )
                if node.returns is not None:
                    for issue in find_annotation_violations(node.returns):
                        problems.append(
                            f"{filename}:{issue} (missing `from __future__ import annotations`)"
                        )
            elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
                for issue in find_annotation_violations(node.annotation):
                    problems.append(
                        f"{filename}:{issue} (missing `from __future__ import annotations`)"
                    )

    return problems


def check_file(path: Path) -> List[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: failed to read file: {exc}"]
    return check_source(source, filename=path.as_posix())


def check_paths(paths: Iterable[Path]) -> List[str]:
    targets: List[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            targets.append(p)
        elif p.is_dir():
            targets.extend(sorted(p.rglob("*.py")))
    violations: List[str] = []
    for py_file in targets:
        if "__pycache__" in py_file.parts:
            continue
        violations.extend(check_file(py_file))
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths",
        nargs="*",
        default=["backend", "packages/sage-core"],
        help="Python files or directories to check (default: backend packages/sage-core)",
    )
    args = parser.parse_args(argv)
    violations = check_paths(Path(p) for p in args.paths)
    if violations:
        print(f"Found {len(violations)} Python 3.8 compatibility violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print("Python 3.8 compatibility gate passed (0 violations).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
