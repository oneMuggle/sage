#!/usr/bin/env python3
"""
symbols.py — 提取源码文件的「能力标识符」, 供 win7-sync 冲突解决时做保留校验。

背景: 2026-11-09 win7-sync PR #2946 中, 4 个 win7 平台 Electron 文件被整文件取
main, 静默回退了 win7 的救援工具能力(TrustedInstaller/wuauserv 检测 + diagnosticPath
对话框变体)。冲突报告只说「按 main 语义为底、win7 增量嫁接」, 但没有给出可核对的
具体清单, 解决者无从发现增量已丢。本模块把「增量」变成可枚举、可自动比对的标识符。

「能力标识符」= 源码里形如 snake_case / camelCase / PascalCase / kebab-case 的标识符
与字符串字面量。刻意排除:
  - 普通小写单词(``state`` / ``idx`` / ``some``)—— 局部变量名, 重命名会造成误报
  - 中文文案 —— 措辞调整频繁, 不适合做硬门禁
  - 注释行 —— 只承载说明, 不承载能力

仅标准库; py38 可运行。
"""
from __future__ import annotations

import re
from typing import Set

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUOTED = re.compile(r"'([A-Za-z][A-Za-z0-9_.\-]*)'")

# Win7 平台扩展文件: main 版本之上叠加了 win7 专属逻辑的文件清单。
# classify_diff.py 把这些文件归为 C 类(平台层收敛), verify_symbol_preservation.py
# 在 CI 阶段对清单内文件做「能力不丢失」硬校验。
# 2026-11-09 PR #2946 回归: 这 4 个文件按 A 类整文件取 main, 丢失 win7
# TrustedInstaller/wuauserv 检测与 diagnosticPath 对话框变体。
WIN7_PLATFORM_FILES = (
    "electron/runtime-check.ts",
    "electron/showStartupFailureDialog.ts",
    "electron/__tests__/runtime-check.test.ts",
    "electron/__tests__/showStartupFailureDialog.test.ts",
)


def _code_lines(text: str) -> list:
    """去掉空行与整行注释, 只留代码行。"""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("*", "//", "/*", "#")):
            continue
        out.append(line)
    return out


def _is_capability_like(token: str) -> bool:
    """snake_case / camelCase / PascalCase / kebab-case, 且长度 >= 4。"""
    if len(token) < 4:
        return False
    if "_" in token or "-" in token or "." in token:
        return True
    return any(ch.isupper() for ch in token)


def capability_symbols(text: str) -> Set[str]:
    """文件里承载「能力」的全部标识符。"""
    out: Set[str] = set()
    for line in _code_lines(text):
        out.update(_IDENT.findall(line))
        out.update(_QUOTED.findall(line))
    return {t for t in out if _is_capability_like(t)}


def capability_loss(base: str, head: str) -> Set[str]:
    """base(合并前 win7)有、head(合并结果)没有的能力标识符。"""
    return capability_symbols(base) - capability_symbols(head)
