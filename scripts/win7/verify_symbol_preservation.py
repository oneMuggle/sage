#!/usr/bin/env python3
"""
verify_symbol_preservation.py — 校验合并到 release/win7 后, win7 平台文件没有丢失
win7 侧的能力标识符。

背景: 2026-11-09 win7-sync PR #2946 把 4 个 win7 平台 Electron 文件整文件取 main,
静默回退了 win7 的救援工具能力(TrustedInstaller/wuauserv 检测 + diagnosticPath
对话框变体)。分类器已把它们改判为 C 类(平台层收敛), 本脚本进一步把「静默丢失」
变成 CI 可检出的失败 —— 即使冲突解决者不看分类报告, 也会被门禁拦下。

用法:
    python scripts/win7/verify_symbol_preservation.py \
        --base origin/release/win7 --head HEAD

--base 取「合并前的 win7 侧」(PR 的 base 分支 tip), --head 取候选合并结果。
清单内文件(symbols.WIN7_PLATFORM_FILES)丢失能力标识符 → 退出码 1(阻断);
其他源文件仅打印提示, 不阻断。

退出码: 0 = 通过; 1 = win7 平台文件有能力标识符丢失; 2 = 用法/环境错误。
仅标准库; py38 可运行。
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
from typing import List, Optional, Set

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from symbols import WIN7_PLATFORM_FILES, capability_loss, capability_symbols  # noqa: E402

SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".pyi")

# 单文件最多打印多少个丢失标识符(超出只报计数)。
# 整文件被 main 版本替换时, 丢失集合可能有上百个, 全量打印会淹没关键信息。
MAX_PRINTED = 40


class VerifyError(RuntimeError):
    pass


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise VerifyError("git {} failed:\n{}".format(" ".join(args), proc.stdout))
    return proc.stdout or ""


def show_blob(ref: str, path: str) -> Optional[str]:
    """取 ref:path 的内容; 文件不存在返回 None。"""
    proc = subprocess.run(
        ["git", "show", "{}:{}".format(ref, path)], cwd=REPO, text=True,
        encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def changed_files(base: str, head: str) -> List[str]:
    out = git("diff", "--name-only", base, head)
    return [line.strip() for line in out.splitlines() if line.strip()]


def check_file(base: str, head: str, path: str) -> Set[str]:
    """返回该文件在 head 相对 base 丢失的能力标识符。"""
    base_text = show_blob(base, path)
    head_text = show_blob(head, path)
    if base_text is None:
        return set()
    if head_text is None:
        # 文件被整体删除 —— 能力标识符全部视为丢失
        return capability_symbols(base_text)
    return capability_loss(base_text, head_text)


def _fmt_symbols(symbols: List[str]) -> str:
    if len(symbols) <= MAX_PRINTED:
        return ", ".join(symbols)
    return "{}, ... 另有 {} 个".format(", ".join(symbols[:MAX_PRINTED]), len(symbols) - MAX_PRINTED)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--base", default="origin/release/win7", help="合并前的 win7 侧 ref")
    ap.add_argument("--head", default="HEAD", help="候选合并结果 ref")
    args = ap.parse_args()

    try:
        files = changed_files(args.base, args.head)
    except VerifyError as exc:
        print("❌ {}".format(exc), file=sys.stderr)
        return 2

    platform = set(WIN7_PLATFORM_FILES)
    failures: list[tuple[str, list[str]]] = []
    warnings: list[tuple[str, list[str]]] = []

    for path in files:
        if not path.endswith(SOURCE_SUFFIXES):
            continue
        lost = check_file(args.base, args.head, path)
        if not lost:
            continue
        entry = (path, sorted(lost))
        if path in platform:
            failures.append(entry)
        else:
            warnings.append(entry)

    print("=== win7 能力标识符保留校验 ===")
    print("- base: {}".format(args.base))
    print("- head: {}".format(args.head))
    print("- 变更文件: {}".format(len(files)))
    print("")

    if warnings:
        print("ℹ️  非平台文件的能力标识符减少（仅提示, 不阻断）:")
        for path, lost in warnings:
            print("   - {}: {}".format(path, _fmt_symbols(lost)))
        print("")

    if failures:
        print("❌ win7 平台文件丢失能力标识符（阻断合并）:")
        for path, lost in failures:
            print("   - {}:".format(path))
            for sym in lost[:MAX_PRINTED]:
                print("       {}".format(sym))
            if len(lost) > MAX_PRINTED:
                print("       ... 另有 {} 个".format(len(lost) - MAX_PRINTED))
        print("")
        print("这些标识符是 win7 侧的平台增量(如 TrustedInstaller/wuauserv 检测、")
        print("diagnosticPath 对话框变体)。合并 main 时必须保留 win7 版本并补齐 main 新增接口,")
        print("不能整文件取 main。参考 docs/win7-sync/parity.md 的 C 类「平台层收敛」处理方式。")
        print("")
        print("若确实要移除某项能力, 请在同一个 PR 里把该文件从")
        print("scripts/win7/symbols.py 的 WIN7_PLATFORM_FILES 中移除(评审可见), 而不是")
        print("无声地让门禁变红后被绕过。")
        print("")
        print("本校验由 scripts/win7/verify_symbol_preservation.py 执行,")
        print("能力标识符清单由 symbols.capability_symbols() 计算。")
        return 1

    print("✅ 无 win7 平台能力标识符丢失")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VerifyError as exc:
        print("❌ {}".format(exc), file=sys.stderr)
        sys.exit(2)
