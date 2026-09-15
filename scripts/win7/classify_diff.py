#!/usr/bin/env python3
"""
classify_diff.py — 将 main...release/win7 的 1,937 异动文件自动分拣为 A/B/C/D 四类
产出: docs/win7-sync/classify.csv + 控制台摘要
"""
import subprocess, pathlib, csv, re, sys, argparse

REPO = pathlib.Path(__file__).resolve().parents[2]
C_PATTERNS = [
    r"^backend/requirements", r"^backend/environment\.yml", r"^electron-builder",
    r"^\.github/workflows/release-win7", r"^scripts/bundle-python\.ps1",
    r"^backend/compat/win7", r"^electron/platform",
]
C_RE = re.compile("|".join(f"({p})" for p in C_PATTERNS))
B_PATTERNS = [
    r"^backend/api/", r"^backend/memory/", r"^backend/orchestration/",
    r"^backend/adapters/out/llm", r"^backend/mcp", r"^backend/data/",
]
B_RE = re.compile("|".join(f"({p})" for p in B_PATTERNS))
D_PATTERNS = [
    r"^\.github/workflows/release-win7", r"^scripts/bundle-python\.ps1",
    r"^resources/build-manifest", r"^backend/requirements-py38",
]
D_RE = re.compile("|".join(f"({p})" for p in D_PATTERNS))

def classify(path: str) -> str:
    if D_RE.search(path):
        return "D"
    if C_RE.search(path):
        return "C"
    if B_RE.search(path):
        return "B"
    return "A"

def get_diff(diff_file=None):
    if diff_file:
        return pathlib.Path(diff_file).read_text(encoding="utf-8").splitlines()
    out = subprocess.check_output(
        ["git", "diff", "--name-only", "origin/main...origin/release/win7"],
        cwd=REPO, text=True
    )
    return [l.strip() for l in out.splitlines() if l.strip()]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", help="已有 diff 文件路径")
    ap.add_argument("--out", default=str(REPO / "docs/win7-sync/classify.csv"))
    args = ap.parse_args()
    files = get_diff(args.diff)
    rows = [(f, classify(f)) for f in files]
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["path", "class", "handler"])
        handler_map = {"A": "cherry-pick 直通","B": "垫片适配 backend/compat/win7","C": "平台层收敛","D": "冻结隔离（不合流）"}
        for p, c in sorted(rows):
            w.writerow([p, c, handler_map[c]])
    from collections import Counter
    cnt = Counter(c for _, c in rows)
    total = len(rows)
    print(f"=== classify done: {total} files ===")
    for k in ["A","B","C","D"]:
        n = cnt.get(k,0)
        print(f"  {k}: {n:4d} ({n/total*100:5.1f}%)")
    print(f"-> {out}")

if __name__ == "__main__":
    main()
