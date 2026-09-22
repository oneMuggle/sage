#!/usr/bin/env python3
"""Circular dependency detector for Python backend.

2026-09-22 (ZCode-inspired optimization): 参考 ZCode 的 architecture policy，
检测 backend/ 内的循环 import 依赖。

用法:
    python scripts/check_circular_deps.py [directory]
    python scripts/check_circular_deps.py backend        # 默认检测 backend/

退出码:
    0 — 无循环依赖
    1 — 发现循环依赖

输出:
    发现循环时打印环路径，如:
    backend/a.py -> backend/b.py -> backend/c.py -> backend/a.py
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


def extract_imports(file_path: Path) -> List[str]:
    """从 Python 文件提取 import 的模块名。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except SyntaxError:
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # 只处理绝对 import
                imports.append(node.module)
    return imports


def build_dependency_graph(
    root_dir: Path,
) -> Tuple[Dict[str, Set[str]], Dict[str, Path]]:
    """构建模块依赖图。返回 (graph, module_to_file)。"""
    graph: Dict[str, Set[str]] = {}
    module_to_file: Dict[str, Path] = {}

    for py_file in root_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        # 将文件路径转为模块名
        rel_path = py_file.relative_to(root_dir.parent)
        module_name = str(rel_path.with_suffix("")).replace(os.sep, ".")
        if module_name.endswith(".__init__"):
            module_name = module_name[: -len(".__init__")]

        module_to_file[module_name] = py_file
        imports = extract_imports(py_file)

        # 只关注内部 import（以 root_dir.name 开头的）
        graph[module_name] = set()
        for imp in imports:
            if imp.startswith(root_dir.name):
                graph[module_name].add(imp)

    return graph, module_to_file


def find_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """使用 DFS 检测图中的循环。"""
    visited: Set[str] = set()
    path: List[str] = []
    path_set: Set[str] = set()
    cycles: List[List[str]] = []

    def dfs(node: str) -> None:
        if node in path_set:
            # 找到环
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        if node in visited:
            return

        path.append(node)
        path_set.add(node)

        for neighbor in graph.get(node, set()):
            dfs(neighbor)

        path.pop()
        path_set.remove(node)
        visited.add(node)

    for node in graph:
        if node not in visited:
            dfs(node)

    return cycles


def main() -> int:
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backend")

    if not target_dir.is_dir():
        print(f"❌ 目录不存在: {target_dir}", file=sys.stderr)
        return 1

    print(f"🔍 检测 {target_dir}/ 的循环依赖...")
    graph, module_to_file = build_dependency_graph(target_dir)

    cycles = find_cycles(graph)

    if not cycles:
        print(f"✅ 未发现循环依赖 (扫描 {len(graph)} 个模块)")
        return 0

    print(f"❌ 发现 {len(cycles)} 个循环依赖:\n")
    for i, cycle in enumerate(cycles, 1):
        print(f"  环 {i}:")
        for module in cycle:
            file_path = module_to_file.get(module)
            file_str = str(file_path) if file_path else module
            print(f"    → {file_str}")
        print()

    print("建议: 重构代码消除循环依赖，常见方法:")
    print("  - 提取共享接口到独立模块")
    print("  - 使用依赖注入而非直接 import")
    print("  - 延迟 import（函数体内 import）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
