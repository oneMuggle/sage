# ruff: noqa: T201, ERA001 — CLI 扫描工具：print 输出即产品形态；docstring 规则示例非注释代码
"""py38 运行期地雷 AST 扫描（win7 LTS 门禁）。

背景：py38 collect 门禁只做 import + pytest --collect-only，能拦住 py39+ 的
*语法*（ast.parse 即报错），但拦不住 py39+ 才有的 *运行期 API/写法*——例如
isinstance 第二参数用类型联合（3.10+）、asyncio.to_thread（3.9+）在函数体内，
import 时毫发无损，跑到那一行才 TypeError。

本脚本用 AST 静态扫描已知的地雷类别，供 CI py38 job 调用；也可本地运行：

    python backend/tools/py38_hazard_scan.py backend

规则（py38 不可用的运行期写法）：
- isinstance 第二参数出现 ``A | B`` 联合（3.10+）
- ``asyncio.to_thread``（3.9+；backend/utils/py_compat.py 垫片自身除外）
- zip 的 strict 关键字（3.10+）
- ``Path.write_text/read_text/write_bytes/readlink(..., newline=)``（3.10+）
- ``Path.hardlink_to``（3.10+）
- ``str.removeprefix/removesuffix``（3.9+）
- ``import zoneinfo / graphlib``（3.9+）
- ``functools.cache``（3.9+）
- ``@dataclass(slots=True / kw_only=True)``（3.10+）

行内写 ``# py38-ok`` 可对单行豁免（须注明原因）。

脚本自身必须 py38 可运行（在 py38 CI job 里执行）。
"""
import ast
import pathlib
import sys

# 整文件豁免（垫片/兼容层自身）
FILE_EXEMPTS = {
    pathlib.PurePosixPath("backend/utils/py_compat.py"),
}

LINE_EXEMPT_MARK = "py38-ok"

# 3.10+ 才有的 Path 方法（3.8 运行即 AttributeError）
PY310_PATH_METHODS = {"hardlink_to"}
# 3.9+ 才有的 Path 方法
PY39_PATH_METHODS = {"is_relative_to"}

# 3.11+ 才有的 datetime 属性（UTC；3.11 以下用 timezone.utc）
PY311_DATETIME_ATTRS = {"UTC"}

# 3.10+ 才有的关键字参数
PY310_KWARGS = {"write_text": {"newline"}, "read_text": {"newline"},
                "write_bytes": {"newline"}, "readlink": {"newline"}}

# 3.9+ 才有的 str 方法（3.8 运行即 AttributeError）
PY39_STR_METHODS = {"removeprefix", "removesuffix"}

# 3.9+ 才有的模块（import 即 ImportError）
PY39_MODULES = {"zoneinfo", "graphlib"}

# 3.9+ 才有的属性（functools.cache；3.8 只有 lru_cache）
PY39_ATTRS = {"cache"}  # 限定 functools.cache 上下文，见 visit_node

# 3.10+ 才有的 @dataclass 参数
PY310_DATACLASS_KWARGS = {"slots", "kw_only"}


def _is_asyncio_to_thread(node):
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "to_thread"
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    )


def visit_node(node, rel, hits):
    # R1: isinstance(x, A | B)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and len(node.args) >= 2
    ):
        for arg in node.args[1:]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                    hits.append((rel, sub.lineno, "isinstance 联合类型 X | Y（3.10+），改元组 (X, Y)"))
                    break

    # R2: asyncio.to_thread
    if _is_asyncio_to_thread(node):
        hits.append((rel, getattr(node, "lineno", 0), "asyncio.to_thread（3.9+），改用 utils.py_compat.to_thread"))

    # R3: zip(strict=...)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "zip"
        and any(kw.arg == "strict" for kw in node.keywords)
    ):
        hits.append((rel, node.lineno, "zip 的 strict 关键字（3.10+）"))

    # R4/R5: Path 3.10+/3.9+ 方法与关键字参数
    if isinstance(node, ast.Attribute) and node.attr in PY310_PATH_METHODS:
        hits.append((rel, node.lineno, f"Path.{node.attr}（3.10+）"))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in PY39_PATH_METHODS
        and isinstance(node.func.value, (ast.Name, ast.Attribute, ast.Constant))  # noqa: UP038 — 脚本自身须 py38 可运行
    ):
        hits.append((rel, node.lineno, "Path.is_relative_to（3.9+），用 os.path.commonpath / 路径解析比较替代"))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        banned = PY310_KWARGS.get(node.func.attr)
        if banned and any(kw.arg in banned for kw in node.keywords):
            hits.append((rel, node.lineno, f"{node.func.attr}(newline=...)（3.10+）"))

    # R12: datetime.UTC（3.11+），用 timezone.utc 替代
    if (
        isinstance(node, ast.Attribute)
        and node.attr in PY311_DATETIME_ATTRS
        and isinstance(node.value, ast.Name)
        and node.value.id == "datetime"
    ):
        hits.append((rel, node.lineno, "datetime 的 UTC 属性（3.11+），用 timezone.utc 替代"))

    # R7: str.removeprefix/removesuffix（3.9+）。限定接收者是 Name/Attribute/
    # 常量字符串——避免把同名自由函数误报进来。
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in PY39_STR_METHODS
        and isinstance(node.func.value, (ast.Name, ast.Attribute, ast.Constant))  # noqa: UP038 — 脚本自身须 py38 可运行
    ):
        hits.append((rel, node.lineno, f"str.{node.func.attr}（3.9+），用 str[start:] / endswith 切片替代"))

    # R8: import zoneinfo / graphlib（3.9+）
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in PY39_MODULES:
                hits.append((rel, node.lineno, f"import {root}（3.9+）"))
    if isinstance(node, ast.ImportFrom) and node.module:
        root = node.module.split(".")[0]
        if root in PY39_MODULES:
            hits.append((rel, node.lineno, f"from {node.module} import ...（3.9+）"))

    # R9: functools.cache（3.9+；3.8 用 lru_cache）
    if (
        isinstance(node, ast.Attribute)
        and node.attr in PY39_ATTRS
        and isinstance(node.value, ast.Name)
        and node.value.id == "functools"
    ):
        hits.append((rel, node.lineno, "functools.cache（3.9+），用 functools.lru_cache(maxsize=None)"))

    # R10: @dataclass(slots=True | kw_only=True)（3.10+）
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dataclass"
        and any(kw.arg in PY310_DATACLASS_KWARGS for kw in node.keywords)
    ):
        hits.append((rel, node.lineno, "@dataclass(slots=/kw_only=)（3.10+）"))


def scan_file(path, rel):
    try:
        src = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    tree = ast.parse(src)
    hits = []
    lines = src.splitlines()
    exempt = {i + 1 for i, ln in enumerate(lines) if LINE_EXEMPT_MARK in ln}
    for node in ast.walk(tree):
        visit_node(node, rel, hits)
    return [h for h in hits if h[1] not in exempt]


def main():
    root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("backend")
    all_hits = []
    for p in sorted(root.rglob("*.py")):
        rel = pathlib.PurePosixPath(p.as_posix())
        if rel in FILE_EXEMPTS:
            continue
        if "__pycache__" in p.parts or "node_modules" in p.parts:
            continue
        try:
            all_hits.extend(scan_file(p, rel))
        except SyntaxError as e:
            # py38 解释器解析 py39+ 语法在此直接报错——同样是地雷
            all_hits.append((rel, e.lineno or 0, f"语法解析失败（py39+ 语法）: {e.msg}"))

    if all_hits:
        print(f"py38 运行期地雷 {len(all_hits)} 处：")
        for rel, lineno, msg in all_hits:
            print(f"  {rel}:{lineno} {msg}")
        print("修复或在该行加 `# py38-ok <原因>` 豁免。")
        return 1
    print(f"py38 运行期地雷扫描：0（{root}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
