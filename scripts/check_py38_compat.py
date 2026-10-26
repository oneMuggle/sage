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
import io
import re
import tokenize
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
    # R96 (2026-09-23): 归一化为 POSIX 分隔符 —— Windows 本地 rel 含反斜杠，
    # "tests/" 片段永远匹配不上，注解检查在 Windows 本地多报（CI/Linux 正常
    # 排除，两侧口径不一致）。
    rel = str(path.relative_to(root)).replace("\\", "/")
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
    # 垫片本身就是双版本适配层，里面必然出现 v2 API 名字
    "compat/win7/pydantic_compat.py",
    # 扫描器的单元测试包含全部地雷字面量（测试样本，非真实代码）
    "tools/test_py38_hazard_scan.py",
    "test_py38_compat_gate.py",
)


def _strip_strings(source: str) -> list[str]:
    """把 STRING / COMMENT 令牌覆盖的字符替换成空格，只留下真正的代码。

    运行时 API 正则必须只看代码：docstring 里写 ``Path.is_relative_to()`` 是在
    说明「这个写法 3.9+ 才有，所以我们不用它」，不是真的调用。按行切 ``#``
    只能去掉注释，去不掉字符串内容。

    令牌失败（源码语法错误）时退回原文，保持旧的按行行为。
    """
    lines = source.splitlines()
    keep = [list(line) for line in lines]
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type not in (tokenize.STRING, tokenize.COMMENT):
                continue
            (start_row, start_col), (end_row, end_col) = tok.start, tok.end
            for row_no in range(start_row, end_row + 1):
                idx = row_no - 1
                if idx < 0 or idx >= len(keep):
                    continue
                begin = start_col if row_no == start_row else 0
                finish = end_col if row_no == end_row else len(keep[idx])
                for col in range(begin, min(finish, len(keep[idx]))):
                    keep[idx][col] = " "
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return lines
    return ["".join(chars) for chars in keep]


def check_runtime_apis(path: Path, root: Path) -> list[tuple[int, str]]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    if any(frag in rel for frag in RUNTIME_SKIP_FRAGMENTS):
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = source.splitlines()
    # 代码视图：字符串/注释被抹成空格，正则只在真正的代码上匹配
    code_lines = _strip_strings(source)
    if len(code_lines) < len(lines):
        code_lines += [""] * (len(lines) - len(code_lines))
    uses_asyncio_wait = "asyncio.wait_for(" in source or "asyncio.timeout(" in source
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        lineno = i + 1
        if PY38_GUARD_MARKER in line:
            i += 1
            continue
        # 字符串与注释已在 code_lines 里被抹成空格；标记判断仍用原始行（标记写在注释里）
        code = code_lines[i]
        # Multi-line calls: `write_text(\n ..., newline="",\n)` — extend the window to the
        # closing paren (max 12 lines) for the call-kwarg patterns.
        window = code
        if "(" in code and ")" not in code.split("(", 1)[1]:
            k = i + 1
            while k < len(lines) and k <= i + 12:
                window += "\n" + code_lines[k]
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
    out.extend(_check_model_rebuild_guards(code_lines, lines))
    out.extend(check_forward_ref_order(source))
    out.extend(_check_pydantic_field_kwargs(source))
    out.sort(key=lambda t: t[0])
    return out



# ── pydantic v1（win7/py38 通道钉 1.10.13）双版本守卫闸门 ────────────────────
#
# compat/win7/pydantic_compat.py 的 install() 会给 v1 的 BaseModel 注入
# model_dump / model_dump_json / model_copy / model_construct / model_validate /
# model_validate_json / model_json_schema 以及 model_fields property，所以那些
# v2 写法在 py38 通道是安全的、不需要拦。
#
# 但 model_rebuild 不在注入列表里 —— pydantic 1.10.13 的 BaseModel 根本没有这个
# 属性。裸调它会在「模块导入期」抛 AttributeError；又因为 FastAPI router 模块会被
# main.py 链式导入，一处裸调就能让整个测试套件在 collection 期全部 E。历史事故：
# #2290 的 CI 日志因此膨胀到 56 MB（11264 个用例全 E，pytest 为每个 error 打印完整
# locals），grep FAILED 什么都搜不到。
#
# 合法写法是双版本守卫：
#     if hasattr(Model, "model_rebuild"):
#         Model.model_rebuild()          # v2
#     else:
#         Model.update_forward_refs()    # v1
MODEL_REBUILD_CALL = re.compile(r"(?<![\w.])(\w+)\.model_rebuild\(\)")
HASATTR_REBUILD_GUARD = re.compile(
    r"hasattr\(\s*(\w+)\s*,\s*[\"'](?:model_rebuild|update_forward_refs)[\"']\s*\)"
)
FOR_LOOP_GUARD = re.compile(r"^\s*for\s+\w+\s+in\s+\(.*\)\s*:")


def _check_model_rebuild_guards(
    code_lines: list[str], lines: list[str]
) -> list[tuple[int, str]]:
    """报出没有双版本守卫的裸 `.model_rebuild()`。

    守卫可以写在调用行上方 6 行内（`if hasattr(M, ...)` 形式），也可以是把调用包在
    `for _cls in (...)` 循环里（backend/office/models.py 末尾那种）—— 后者的调用
    对象是循环变量，无法静态关联到具体类名，所以只要该行处在一个含 hasattr 守卫的
    for 循环体内就豁免。

    关键细节：守卫名本身写在字符串里（hasattr(X, "model_rebuild")），而 code_lines
    已把字符串抹成空格，所以**守卫必须用原始行 lines 匹配，调用才用 code_lines**。
    """
    out: list[tuple[int, str]] = []
    for i, code in enumerate(code_lines):
        if ".model_rebuild(" not in code:
            continue
        if PY38_GUARD_MARKER in lines[i]:
            continue
        lineno = i + 1
        window = "\n".join(lines[max(0, i - 6):i + 1])
        guarded = set(HASATTR_REBUILD_GUARD.findall(window))
        called = set(MODEL_REBUILD_CALL.findall(code))
        if called and called <= guarded:
            continue
        in_guarded_loop = False
        for j in range(max(0, i - 6), i):
            if FOR_LOOP_GUARD.match(code_lines[j]):
                body = "\n".join(lines[j:i + 1])
                if "hasattr(" in body and (
                    "update_forward_refs" in body or "model_rebuild" in body
                ):
                    in_guarded_loop = True
                    break
        if in_guarded_loop:
            continue
        out.append((lineno, (
            "py38 runtime: bare `.model_rebuild()` is pydantic-v2-only and the win7 "
            "compat shim does NOT inject it (install() covers model_dump/validate/"
            "copy/construct/json_schema/fields only). On pydantic 1.10.13 this raises "
            "AttributeError at IMPORT time, which cascades through the FastAPI router "
            "chain and errors out the entire test suite at collection. Wrap it: "
            '`if hasattr(M, "model_rebuild"): M.model_rebuild() '
            "else: M.update_forward_refs()`"
        )))
    return out


# ── pydantic v2 已移除的 Field kwargs 守卫 ───────────────────────────────────
#
# pydantic v2 移除了 Field() 的若干关键字参数, 失败形态有两种:
#   - ``regex=``      v2 直接抛 PydanticUserError(removed-kwargs) —— 模块**导入期**就炸;
#   - ``min_items=``  v2 静默收进 json_schema_extra, 约束**静默失效**(比报错更危险)。
#
# 两个 CI 通道都看不见这类问题:
#   - py38 通道钉 pydantic 1.10.13, 上述 kwargs 在 v1 全部合法 ⇒ 该通道必然绿;
#   - 唯一能跑 pydantic 2.5 的 job「Backend (Python)」在本仓配置里是 SKIPPED。
#
# 历史事故 (#2550 → #2555): legacy_memory_routes.py 写了
# ``feedback: str = Field(regex="^(up|down)$")``, 使 backend.main 在 pydantic 2.x
# 下无法导入; 又因 conftest 的 setup_test_db 是 autouse, 整个套件在 setup 期全 E。
# 该端点本来有 19 个测试用例, 但模块导入期就炸, 连 collection 都过不去 ——
# 覆盖存在却完全不可见, 所以静态守卫是这里唯一的兜底。
#
# 仓库约定: 业务代码写 v2 风格 ``pattern=``, v1 通道由
# backend/compat/win7/pydantic_compat.py 的 install() 把 pattern 转译成 regex。
REMOVED_FIELD_KWARGS = {
    "regex": "pattern",
    "min_items": "min_length",
    "max_items": "max_length",
    "unique_items": "(v2 无直接替代: 去掉约束或改用 field_validator)",
    "allow_mutation": "frozen",
    "const": "Literal",
}


def _check_pydantic_field_kwargs(source: str) -> list[tuple[int, str]]:
    """报出 ``Field(...)`` 上用到的 pydantic v2 已移除关键字参数。

    只认 callee 末段为 ``Field`` 的调用 (``Field`` / ``pydantic.Field``), 因此
    JSON schema 字典里的同名键、或普通函数同名的参数不会被误报。用 AST 判定而非
    正则, 是为了正确处理跨行的 ``Field(\n    regex=...\n)``。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = getattr(func, "id", None) or getattr(func, "attr", None)
        if callee != "Field":
            continue
        for kw in node.keywords:
            if kw.arg is None:
                continue
            replacement = REMOVED_FIELD_KWARGS.get(kw.arg)
            if replacement is None:
                continue
            out.append(
                (
                    node.lineno,
                    "pydantic v2 removed `Field(%s=...)` (use %s)" % (kw.arg, replacement),
                )
            )
    out.sort(key=lambda t: t[0])
    return out


def _annotation_names(node: ast.AST | None) -> set[str]:
    """收集注解表达式里出现的所有裸名字（含下标/字符串形式的前向引用）。"""
    names: set[str] = set()
    if node is None:
        return names
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            pass
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            # 字符串形式的前向引用："WordIndexSpec" / "Optional[X]"
            for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sub.value):
                names.add(tok)
    return names


def _is_pydantic_base(node: ast.ClassDef, pydantic: set[str]) -> bool:
    """判断 ClassDef 是否（可能）是 pydantic 模型。

    只看基类名字的末段（`pydantic.BaseModel` → `BaseModel`），并认本文件里已判定为
    pydantic 的类名 —— 这样 `class WordFormatSpec(BaseModel)` 的子类也能识别。
    不用子串猜测（之前用 "Model"/"Schema" 子串匹配，把 BaseHTTPRequestHandler
    之类误判成 pydantic 类）。
    """
    for b in node.bases:
        name = None
        if isinstance(b, ast.Name):
            name = b.id
        elif isinstance(b, ast.Attribute):
            name = b.attr
        if not name:
            continue
        if name in ("BaseModel", "BaseSettings") or name in pydantic:
            return True
    return False


def check_forward_ref_order(source: str) -> list[tuple[int, str]]:
    """报出「pydantic 模型的**字段**注解引用了本文件里更晚定义的类、且无守卫」。

    pydantic v1 在类创建期就解析注解；被引用的名字若此刻还没绑定到模块命名空间，
    就会留下 ForwardRef，首次使用时抛 ConfigError（"field X not yet prepared"）。
    v2 惰性解析，所以本地 pydantic 2.x 环境完全测不出来 —— 这条规则存在的理由。

    两种合法解法：
      (a) 把被引用的类定义在使用点之前（win7 对 WordSectionBreakSpec / WordIndexSpec
          用的就是这个，且 docstring 写明了原因）；
      (b) 对该类调 update_forward_refs()/model_rebuild() 守卫（win7 对
          OfficeWordReadResult / ExcelSheetSpec / ExcelPrintSetupSpec 用这个）。

    实现要点（都是踩过的坑）：
      * 用 ast 而不是正则判「类字段」—— 正则按缩进猜会把**方法体内的局部变量注解**
        和**方法参数注解**也算成字段（mock_server.py 的 `state: MockLLMServer`、
        download_tool.py 的 `ctx: _DownloadContext` 就是这样被误报的）。
      * 只扫 ClassDef.body 里直接的 AnnAssign，不进任何 FunctionDef。
      * 只对 pydantic 模型生效；普通类 / dataclass / abc.ABC / BaseHTTPRequestHandler
        的注解不在创建期解析，前向引用完全无害。
    """
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    # 1) 所有类定义的行号
    classdef_line: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classdef_line.setdefault(node.name, node.lineno)

    # 2) 自底向上两趟，判定哪些类是 pydantic 模型（子类可能引用父类）
    pydantic: set[str] = set()
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for _ in range(3):
        changed = False
        for node in classes:
            if node.name in pydantic:
                continue
            if _is_pydantic_base(node, pydantic):
                pydantic.add(node.name)
                changed = True
        if not changed:
            break
    if not pydantic:
        return []

    # 3) 守卫集合：从原始行提取（守卫名写在字符串里，_strip_strings 会抹掉）
    guarded: set[str] = set()
    for i, line in enumerate(lines):
        for m in HASATTR_REBUILD_GUARD.finditer(line):
            guarded.add(m.group(1))
        for m in re.finditer(
            r"\b([A-Z][A-Za-z0-9_]*)\.(?:update_forward_refs|model_rebuild)\(\)", line
        ):
            guarded.add(m.group(1))
        if FOR_LOOP_GUARD.match(line) and "(" in line and ")" in line:
            body = "\n".join(lines[i + 1:i + 6])
            if "update_forward_refs" in body or "model_rebuild" in body:
                inner = line[line.index("(") + 1:line.rindex(")")]
                for nm in re.findall(r"[A-Z][A-Za-z0-9_]*", inner):
                    guarded.add(nm)

    # 4) 扫 pydantic 类的**直接** AnnAssign 字段
    out: list[tuple[int, str]] = []
    seen: set[tuple[str, str]] = set()
    for node in classes:
        if node.name not in pydantic or node.name in guarded:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            field = stmt.target.id
            for ident in _annotation_names(stmt.annotation):
                defined_at = classdef_line.get(ident)
                if defined_at is None or defined_at <= stmt.lineno:
                    continue
                key = (node.name, field)
                if key in seen:
                    continue
                seen.add(key)
                out.append((stmt.lineno, (
                    "py38 runtime: `%s.%s` forward-references `%s`, which is only "
                    "defined at line %d. pydantic v1 resolves annotations at class-"
                    "creation time, so this stays an unresolved ForwardRef and the "
                    'first use raises ConfigError ("field %s not yet prepared"). '
                    "pydantic v2 resolves lazily, so local envs (2.x) do NOT catch "
                    "this. Fix: move `class %s` above `%s`, or add an "
                    "update_forward_refs()/model_rebuild() guard for `%s`."
                    % (node.name, field, ident, defined_at, field, ident,
                       node.name, node.name)
                )))
                break
    out.sort(key=lambda t: t[0])
    return out


MODEL_SUFFIXES = ("Model", "Schema", "Request", "Response")
ROUTE_METHODS = frozenset({"get", "post", "put", "delete", "patch", "websocket", "api_route"})


def _find_annotation_violations(node: ast.AST) -> list[str]:
    issues: list[str] = []
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


def check_source(source: str, filename: str = "<string>") -> list[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"{filename}:{exc.lineno or '?'}: syntax error: {exc.msg}"]
    has_future = any(
        isinstance(n, ast.ImportFrom)
        and n.module == "__future__"
        and any(a.name == "annotations" for a in n.names)
        for n in tree.body
    )
    problems: list[str] = []
    for node in ast.walk(tree):
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
        if isinstance(node, ast.ClassDef) and any(
            (isinstance(b, ast.Name) and any(s in b.id for s in MODEL_SUFFIXES))
            or (isinstance(b, ast.Attribute) and any(s in b.attr for s in MODEL_SUFFIXES))
            for b in node.bases
        ):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and stmt.annotation is not None:
                    for issue in _find_annotation_violations(stmt.annotation):
                        problems.append(f"{filename}:{issue} in Pydantic model `{node.name}`")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr in ROUTE_METHODS
            for d in node.decorator_list
        ):
            args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
            for arg in args:
                if arg.annotation is not None:
                    for issue in _find_annotation_violations(arg.annotation):
                        problems.append(
                            f"{filename}:{issue} in FastAPI route `{node.name}` param `{arg.arg}`"
                        )
            if node.returns is not None:
                for issue in _find_annotation_violations(node.returns):
                    problems.append(
                        f"{filename}:{issue} in FastAPI route `{node.name}` return annotation"
                    )
        if not has_future:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
                for arg in args:
                    if arg.annotation is not None:
                        for issue in _find_annotation_violations(arg.annotation):
                            problems.append(
                                f"{filename}:{issue} (missing `from __future__ import annotations`)"
                            )
                if node.returns is not None:
                    for issue in _find_annotation_violations(node.returns):
                        problems.append(
                            f"{filename}:{issue} (missing `from __future__ import annotations`)"
                        )
            elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
                for issue in _find_annotation_violations(node.annotation):
                    problems.append(
                        f"{filename}:{issue} (missing `from __future__ import annotations`)"
                    )
    # 运行期双版本守卫检查也要走这条通路 —— 否则自测（用 check_source）测不到，
    # 而 CI 全仓扫描（用 check_runtime_apis）能测到，两条通路结果不一致。
    _lines = source.splitlines()
    _code_lines = _strip_strings(source)
    if len(_code_lines) < len(_lines):
        _code_lines += [""] * (len(_lines) - len(_code_lines))
    for _ln, _msg in _check_model_rebuild_guards(_code_lines, _lines):
        problems.append(f"{filename}:{_ln}: {_msg}")
    for _ln, _msg in check_forward_ref_order(source):
        problems.append(f"{filename}:{_ln}: {_msg}")
    for _ln, _msg in _check_pydantic_field_kwargs(source):
        problems.append(f"{filename}:{_ln}: {_msg}")
    return problems


def check_paths(paths: list[Path]) -> list[str]:
    targets: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            targets.append(p)
        elif p.is_dir():
            targets.extend(sorted(p.rglob("*.py")))
    violations: list[str] = []
    for py_file in targets:
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.as_posix()
        if any(frag in rel for frag in SKIP_PATH_FRAGMENTS):
            continue
        try:
            src = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        violations.extend(check_source(src, filename=rel))
    return violations


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