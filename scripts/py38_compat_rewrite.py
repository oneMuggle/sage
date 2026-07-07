#!/usr/bin/env python3
"""Rewrite PEP 604 (X | None) and PEP 585 (list[int]) type annotations to
Py3.8-compatible typing.* equivalents in backend/ and packages/sage-core/.

Why: Win7 LTS bundles Python 3.8.10 (last Win7-supporting version).
- PEP 604 (X | Y union syntax): Py3.10+ runtime; Py3.8/3.9 raise
  TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'.
  Pydantic 1.x's resolve_annotations evaluates these strings at runtime
  via typing.get_type_hints(), so even with `from __future__ import
  annotations` the runtime still chokes.
- PEP 585 (built-in generics: list[int], dict[str, int]): Py3.9+ runtime.
  Same runtime evaluation issue.

Fix: rewrite annotation expressions to use typing.Optional/Union/List/Dict/etc.
These work on all Python 3.x versions. Adds needed imports automatically.

Idempotent: running twice produces no further changes.

Run:
    python3 scripts/py38_compat_rewrite.py backend/ packages/sage-core/

Verification:
    git diff --stat
    git diff <file>
    pytest backend/  # on Python 3.10+ to ensure no regression
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Set

import libcst as cst
import libcst.matchers as m

# PEP 585 → typing.* mapping. We must NOT rewrite these if already wrapped in
# typing.List/etc. — only the BUILTIN form.
PEP585_BUILTINS = {
    "list": "List",
    "dict": "Dict",
    "tuple": "Tuple",
    "set": "Set",
    "frozenset": "FrozenSet",
    "type": "Type",
}

# typing import names we may need to add.
TYPING_NAMES = {
    "Optional", "Union",
    "List", "Dict", "Tuple", "Set", "FrozenSet", "Type",
}

# Node matcher for builtin generic subscription. e.g. list[int], dict[str, int].
BUILTIN_GENERIC_MATCHER = m.Subscript(
    value=m.Name("list") | m.Name("dict") | m.Name("tuple")
    | m.Name("set") | m.Name("frozenset") | m.Name("type")
)


def _is_none(node: cst.CSTNode) -> bool:
    return isinstance(node, cst.Name) and node.value == "None"


def _contains_none(nodes: Iterable[cst.CSTNode]) -> bool:
    for n in nodes:
        if _is_none(n):
            return True
    return False


def _build_optional(inner: cst.CSTNode) -> cst.BaseExpression:
    """Wrap an expression in Optional[...]."""
    return cst.Subscript(
        value=cst.Name("Optional"),
        slice=[cst.SubscriptElement(slice=cst.Index(value=inner))],
    )


def _build_union(nodes: list[cst.BaseExpression]) -> cst.BaseExpression:
    """Build a nested Union[A, B, C] from a list of nodes (Union is binary,
    so multi-type becomes Union[A, Union[B, C]])."""
    if not nodes:
        raise ValueError("empty union")
    if len(nodes) == 1:
        return nodes[0]
    head, tail = nodes[0], nodes[1:]
    return cst.Subscript(
        value=cst.Name("Union"),
        slice=[
            cst.SubscriptElement(slice=cst.Index(value=head)),
            cst.SubscriptElement(
                slice=cst.Index(value=_build_union(tail)),
            ),
        ],
    )


class AnnotationRewriter(cst.CSTTransformer):
    """Rewrites PEP 604 / PEP 585 in type-annotation positions only.

    An annotation position is:
      - FunctionAnnotation on params / return
      - AnnAssign annotation (`: int | None = ...`)
      - TypeAlias (PEP 613): `MyAlias = int | str`

    We do NOT rewrite unions elsewhere (e.g. expression bodies like
    `some_set | other_set`, dict union, etc.).
    """

    def __init__(self) -> None:
        super().__init__()
        self.changed = False
        self.needs_typing_imports: Set[str] = set()

    # ------------------------------------------------------------------
    # Annotation positions — only entry points.
    #
    # NOTE on libcst hook signatures:
    # - Node-level hooks (`leave_Param`, `leave_FunctionReturn`,
    #   `leave_AnnAssign`, `leave_TypeAlias`) are called with
    #   `(original_node, updated_node)` and their RETURN VALUE replaces
    #   updated_node. These are how we modify the tree.
    # - Attribute-level hooks (`leave_Param_annotation`, etc.) are
    #   state-management only — their return value is DISCARDED by
    #   on_leave_attribute. So they CANNOT mutate the tree; we MUST
    #   use the node-level hooks instead.
    # ------------------------------------------------------------------

    def leave_Param(
        self, original_node: cst.Param, updated_node: cst.Param
    ) -> cst.Param:
        if updated_node.annotation is None:
            return updated_node
        inner = updated_node.annotation.annotation
        new_inner = self._rewrite_annotation(inner)
        if new_inner is inner:
            return updated_node
        self.changed = True
        new_annotation = updated_node.annotation.with_changes(annotation=new_inner)
        return updated_node.with_changes(annotation=new_annotation)

    def leave_FunctionReturn(
        self, original_node: cst.FunctionReturn, updated_node: cst.FunctionReturn
    ) -> cst.FunctionReturn:
        if updated_node.annotation is None:
            return updated_node
        inner = updated_node.annotation.annotation
        new_inner = self._rewrite_annotation(inner)
        if new_inner is inner:
            return updated_node
        self.changed = True
        new_annotation = updated_node.annotation.with_changes(annotation=new_inner)
        return updated_node.with_changes(annotation=new_annotation)

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign:
        if updated_node.annotation is None:
            return updated_node
        inner = updated_node.annotation.annotation
        new_inner = self._rewrite_annotation(inner)
        if new_inner is inner:
            return updated_node
        self.changed = True
        new_annotation = updated_node.annotation.with_changes(annotation=new_inner)
        return updated_node.with_changes(annotation=new_annotation)

    def leave_TypeAlias(
        self, original_node: cst.TypeAlias, updated_node: cst.TypeAlias
    ) -> cst.TypeAlias:
        new_value = self._rewrite_annotation(updated_node.value)
        if new_value is updated_node.value:
            return updated_node
        self.changed = True
        return updated_node.with_changes(value=new_value)

    # ------------------------------------------------------------------
    # Core rewrite: a union expression -> Optional / Union.
    # ------------------------------------------------------------------

    def _rewrite_annotation(self, expr: cst.BaseExpression) -> cst.BaseExpression:
        """If `expr` is a BitOr (PEP 604 union), rewrite to Optional/Union.
        Else, just rewrite PEP 585 builtins within it (recurse via leave_*).
        """
        if isinstance(expr, cst.BinaryOperation) and isinstance(expr.operator, cst.BitOr):
            operands = self._flatten_or(expr)
            # Recursively rewrite each operand (handles nested generics + unions).
            operands = [self._rewrite_pep585_in_expr(o) for o in operands]
            new_expr = self._build_union_expr(operands)
            self.changed = True
            return new_expr
        # No union — just recursively rewrite PEP 585 builtins in nested subscripts.
        new_expr = self._rewrite_pep585_in_expr(expr)
        return new_expr

    def _flatten_or(self, expr: cst.BinaryOperation) -> list[cst.BaseExpression]:
        """Flatten left-associative chain of BitOr into a flat list."""
        result: list[cst.BaseExpression] = []
        def _walk(e: cst.BaseExpression) -> None:
            if isinstance(e, cst.BinaryOperation) and isinstance(e.operator, cst.BitOr):
                _walk(e.left)
                _walk(e.right)
            else:
                result.append(e)
        _walk(expr)
        return result

    def _build_union_expr(
        self, operands: list[cst.BaseExpression]
    ) -> cst.BaseExpression:
        """If any operand is None, wrap the rest in Optional[...]."""
        none_idxs = [i for i, op in enumerate(operands) if _is_none(op)]
        if none_idxs:
            non_none = [op for i, op in enumerate(operands) if i not in none_idxs]
            self.needs_typing_imports.add("Optional")
            if len(non_none) == 1:
                return _build_optional(non_none[0])
            self.needs_typing_imports.add("Union")
            inner_union = _build_union(non_none)
            return _build_optional(inner_union)
        # No None — plain Union if 2+ types, else identity.
        if len(operands) == 1:
            return operands[0]
        self.needs_typing_imports.add("Union")
        return _build_union(operands)

    # ------------------------------------------------------------------
    # PEP 585: list[int] → List[int]
    # ------------------------------------------------------------------

    def leave_Subscript(
        self, original_node: cst.Subscript, updated_node: cst.Subscript
    ) -> cst.BaseExpression:
        return self._convert_pep585(updated_node)

    def _rewrite_pep585_in_expr(self, expr: cst.BaseExpression) -> cst.BaseExpression:
        """Walk the expression tree and convert any PEP 585 subscripts found.
        Use libcst.findall / recursive replace via leave_Subscript below.
        """
        # Just return expr; the leave_Subscript hook will fire on the whole
        # subtree when we leave it.
        return expr

    def _convert_pep585(self, node: cst.BaseExpression) -> cst.BaseExpression:
        """Recursively convert PEP 585 builtin subscripts to typing.* subscripts,
        AND recurse into slice contents to rewrite any nested PEP 604 / PEP 585.
        Returns a (possibly new) expression.
        """
        if not isinstance(node, cst.Subscript):
            return node
        # Only convert when value is a Name matching a builtin generic.
        if not isinstance(node.value, cst.Name):
            return node
        builtin_name = node.value.value
        if builtin_name not in PEP585_BUILTINS:
            return node
        typing_name = PEP585_BUILTINS[builtin_name]
        # Recursively rewrite the slice contents (handles nested cases):
        # PEP 604 (int | None) and PEP 585 (list[X]) inside slice.
        new_slice: list[cst.SubscriptElement] = []
        for elt in node.slice:
            if isinstance(elt.slice, cst.Index):
                inner_val = elt.slice.value
                # If the slice contains a union, rewrite to Optional/Union first.
                if isinstance(inner_val, cst.BinaryOperation) and isinstance(
                    inner_val.operator, cst.BitOr
                ):
                    operands = self._flatten_or(inner_val)
                    operands = [self._convert_pep585(o) for o in operands]
                    inner_val = self._build_union_expr(operands)
                else:
                    inner_val = self._convert_pep585(inner_val)
                new_slice.append(
                    elt.with_changes(slice=cst.Index(value=inner_val))
                )
            else:
                new_slice.append(elt)
        self.changed = True
        self.needs_typing_imports.add(typing_name)
        return node.with_changes(
            value=cst.Name(typing_name), slice=new_slice
        )


class TypingImportAdder(cst.CSTTransformer):
    """Add `from typing import ...` for names used by AnnotationRewriter.
    Idempotent: never duplicates an existing import.
    """

    def __init__(self, needed: Set[str]) -> None:
        super().__init__()
        self.needed = needed

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        if not self.needed:
            return updated_node
        # Find existing `from typing import ...` (or typing.X aliases).
        existing_names: Set[str] = set()
        existing_aliases: dict[str, str] = {}  # alias -> canonical name
        typing_import_idx: int | None = None
        for idx, stmt in enumerate(updated_node.body):
            if (
                isinstance(stmt, cst.SimpleStatementLine)
                and len(stmt.body) == 1
                and isinstance(stmt.body[0], cst.ImportFrom)
                and stmt.body[0].module
                and stmt.body[0].module.value == "typing"
            ):
                typing_import_idx = idx
                for alias in stmt.body[0].names:
                    if isinstance(alias.name, cst.Name):
                        existing_names.add(alias.name.value)
                    if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
                        existing_aliases[alias.asname.name.value] = (
                            alias.name.value if isinstance(alias.name, cst.Name) else ""
                        )
        to_add = sorted(self.needed - existing_names)
        if not to_add:
            return updated_node
        new_aliases = [
            cst.ImportAlias(
                name=cst.Name(n),
                comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" ")),
            )
            for n in to_add
        ]
        # Last alias MUST NOT have a comma (Python does not allow trailing
        # commas in non-parenthesized from-imports). We default to no
        # trailing comma; the merge path will re-attach commas correctly.
        if new_aliases:
            new_aliases[-1] = new_aliases[-1].with_changes(
                comma=cst.MaybeSentinel.DEFAULT
            )
        new_import = cst.ImportFrom(
            module=cst.Name("typing"),
            names=new_aliases,
        )
        new_stmt = cst.SimpleStatementLine(body=[new_import])
        if typing_import_idx is not None:
            # Merge with existing typing import.
            existing_stmt = updated_node.body[typing_import_idx]
            assert isinstance(existing_stmt, cst.SimpleStatementLine)
            existing_import = existing_stmt.body[0]
            assert isinstance(existing_import, cst.ImportFrom)
            # Strip ALL commas from existing aliases (we'll re-add correctly
            # after merging + sorting to avoid dangling trailing commas that
            # break non-parenthesized imports).
            existing_aliases = [
                a.with_changes(comma=cst.MaybeSentinel.DEFAULT)
                for a in existing_import.names
            ]
            combined = existing_aliases + new_aliases
            # Sort alphabetically by name for stable diff (canonicalizing).
            combined.sort(
                key=lambda a: a.name.value if isinstance(a.name, cst.Name) else ""
            )
            # Last item MUST have no comma (trailing commas invalid in
            # non-parenthesized from-imports). All preceding items get a comma.
            for i in range(len(combined) - 1):
                combined[i] = combined[i].with_changes(
                    comma=cst.Comma(
                        whitespace_after=cst.SimpleWhitespace(" ")
                    )
                )
            # Last item: ensure DEFAULT (no comma).
            if combined:
                combined[-1] = combined[-1].with_changes(
                    comma=cst.MaybeSentinel.DEFAULT
                )
            new_existing = existing_import.with_changes(names=combined)
            new_existing_stmt = existing_stmt.with_changes(body=[new_existing])
            new_body = list(updated_node.body)
            new_body[typing_import_idx] = new_existing_stmt
        else:
            # Insert after docstring (if any) and __future__ imports.
            insert_at = 0
            for i, stmt in enumerate(updated_node.body):
                if (
                    isinstance(stmt, cst.SimpleStatementLine)
                    and len(stmt.body) == 1
                    and (
                        # docstring
                        (
                            isinstance(stmt.body[0], cst.Expr)
                            and isinstance(stmt.body[0].value, cst.SimpleString)
                        )
                        # `from __future__ import ...`
                        or (
                            isinstance(stmt.body[0], cst.ImportFrom)
                            and stmt.body[0].module
                            and stmt.body[0].module.value == "__future__"
                        )
                    )
                ):
                    insert_at = i + 1
                else:
                    break
            new_body = list(updated_node.body)
            new_body.insert(insert_at, new_stmt)
        return updated_node.with_changes(body=new_body)


def transform_file(path: Path) -> bool:
    """Rewrite one .py file in-place. Returns True if changed."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = cst.parse_module(source)
    except cst.ParserSyntaxError as e:
        print(f"  ! parse error: {e}", file=sys.stderr)
        return False

    rewriter = AnnotationRewriter()
    new_tree = tree.visit(rewriter)
    if rewriter.changed:
        adder = TypingImportAdder(rewriter.needs_typing_imports)
        new_tree = new_tree.visit(adder)
        path.write_text(new_tree.code, encoding="utf-8")
    return rewriter.changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("paths", nargs="+", help="files or directories to rewrite")
    parser.add_argument(
        "--check",
        action="store_true",
        help="only report which files would change, don't write",
    )
    args = parser.parse_args()

    targets: list[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_file() and path.suffix == ".py":
            targets.append(path)
        elif path.is_dir():
            targets.extend(sorted(path.rglob("*.py")))
        else:
            print(f"  ! skip (not a file/dir): {p}", file=sys.stderr)

    changed = 0
    unchanged = 0
    for path in targets:
        # Skip __pycache__, generated files
        if "__pycache__" in path.parts:
            continue
        if args.check:
            source = path.read_text(encoding="utf-8")
            try:
                tree = cst.parse_module(source)
            except cst.ParserSyntaxError:
                continue
            r = AnnotationRewriter()
            tree.visit(r)
            if r.changed:
                print(f"would rewrite: {path}")
                changed += 1
            else:
                unchanged += 1
        else:
            if transform_file(path):
                print(f"rewrote: {path}")
                changed += 1
            else:
                unchanged += 1

    print(f"\nSummary: {changed} changed, {unchanged} unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())