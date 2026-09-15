#!/usr/bin/env python3
"""
parity_report.py — 生成 win7 vs main 的对齐度看板（机器部分）

输出 docs/win7-sync/parity-auto.md（+ 可选 JSON）。手工维护的批次表/经验在
docs/win7-sync/parity.md，本脚本**不再覆盖**它。

残差分级（B4-B6 审计沉淀）：
  typing-only : 去掉 py38 typing 回写行后 hunk 为空 → win7 必要差异，无需动作
  frozen (D)  : 发布/打包冻结件 → 永不合流
  intentional : 命中 docs/win7-sync/parity-allow.txt（B4-B6 审计登记的必要差异）
  win7-only   : main 无此文件（win7 独有）→ 需确认仍有 importer，否则删
  main-only   : win7 无此文件 → 漏合入，需处理
  real        : 有实质业务差异 → 需人工审阅

用法：
    python scripts/win7/parity_report.py                      # 对比 origin/main vs HEAD
    python scripts/win7/parity_report.py --base origin/main --head origin/release/win7
    python scripts/win7/parity_report.py --fail-on main-only,real,win7-only   # CI 守门
    python scripts/win7/parity_report.py --write-allow                # 审计收口后登记
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from collections import Counter
from typing import Dict, List

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "win7"))
from classify_diff import classify  # noqa: E402

def sh(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8", errors="replace"
    ).strip()


# ---- 归一化：把 py38 typing 回写 / pydantic 垫片 import 折叠成同一形态 ----
_GENERICS = ("List", "Dict", "Tuple", "Set", "FrozenSet", "Type")
_SHIM_NAMES = ("field_validator", "model_validator", "ConfigDict", "computed_field")


def _fold_optional(s: str) -> str:
    """Optional[X] → X | None，正确处理嵌套括号。"""
    key = "Optional["
    while True:
        i = s.find(key)
        if i < 0:
            return s
        depth, j = 0, i + len(key)
        while j < len(s):
            if s[j] == "[":
                depth += 1
            elif s[j] == "]":
                if depth == 0:
                    break
                depth -= 1
            j += 1
        inner = s[i + len(key):j]
        s = s[:i] + inner + " | None" + s[j + 1:]


def normalize(line: str) -> str:
    s = line
    s = re.sub(r"\bbuiltins\.(list|dict|tuple|set|frozenset|type)\[", r"\1[", s)
    s = _fold_optional(s)
    s = re.sub(r"\b(%s)\[" % "|".join(_GENERICS), lambda m: m.group(1).lower() + "[", s)
    # isinstance(x, (A, B)) ⇔ isinstance(x, A | B)
    s = re.sub(r"isinstance\(([^,]+),\s*\(([^()]+)\)\)",
               lambda m: "isinstance({}, {})".format(
                   m.group(1), " | ".join(t.strip() for t in m.group(2).split(",") if t.strip())), s)
    s = re.sub(r"\s*\|\s*", " | ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _import_names(line: str):
    """`from X import a, b` → (X, {a,b})；否则 None。"""
    m = re.match(r"\s*from\s+([\w.]+)\s+import\s+(.+)$", line)
    if not m:
        return None
    names = {n.strip().split(" as ")[0] for n in m.group(2).strip("() ").split(",") if n.strip()}
    return m.group(1), names


def fold_imports(lines: List[str]) -> List[str]:
    """合并同侧 import：typing 行整体丢弃（回写会增删它们）；pydantic + compat 垫片
    的名字合并成一行 `from pydantic import …`，使两侧可比。"""
    pyd = set()
    out = []
    for ln in lines:
        parsed = _import_names(ln)
        if parsed:
            mod, names = parsed
            if mod == "typing":
                continue
            if mod == "pydantic" or mod.endswith("pydantic_compat"):
                pyd |= names
                continue
        out.append(ln)
    if pyd:
        out.append("from pydantic import " + ", ".join(sorted(pyd)))
    return out


def load_allow(path: pathlib.Path) -> List[str]:
    """允许清单：每行一个 glob（fnmatch），# 开头为注释。命中的 real/win7-only 记为 intentional。"""
    if not path.is_file():
        return []
    pats = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            pats.append(line)
    return pats


def is_allowed(path: str, pats: List[str]) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(path, p) for p in pats)


def grade_file(status: str, path: str, base: str, head: str) -> str:
    if classify(path) == "D":
        return "frozen"
    if status == "A":  # 在 head 有、base 无 → 以 base=main 视角就是 win7-only
        return "win7-only"
    if status == "D":
        return "main-only"
    diff = sh("diff", "-U0", "--no-color", base, head, "--", path)
    minus, plus = [], []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            plus.append(line[1:])
        elif line.startswith("-"):
            minus.append(line[1:])
    nm = Counter(normalize(x) for x in fold_imports(minus))
    npl = Counter(normalize(x) for x in fold_imports(plus))
    nm.pop("", None)
    npl.pop("", None)
    return "typing-only" if nm == npl else "real"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main", help="main 侧")
    ap.add_argument("--head", default="HEAD", help="win7 侧")
    ap.add_argument("--out", default=str(REPO / "docs/win7-sync/parity-auto.md"))
    ap.add_argument("--json", default=None)
    ap.add_argument("--fail-on", default="", help="逗号分隔的等级，出现即非零退出（如 main-only,real,win7-only）")
    ap.add_argument("--max-list", type=int, default=60)
    ap.add_argument("--allow", default=str(REPO / "docs/win7-sync/parity-allow.txt"),
                    help="已审计的 win7 必要差异清单（glob/行）；命中 → intentional")
    ap.add_argument("--write-allow", action="store_true",
                    help="把当前 real + win7-only 全部写入 --allow（审计收口时用一次）")
    args = ap.parse_args()
    allow = load_allow(pathlib.Path(args.allow))

    base_sha = sh("rev-parse", "--short", args.base)
    head_sha = sh("rev-parse", "--short", args.head)
    try:
        ahead_main, ahead_win7 = sh(
            "rev-list", "--left-right", "--count", "{}...{}".format(args.base, args.head)).split()
    except Exception:
        ahead_main = ahead_win7 = "?"
    merge_base = sh("merge-base", args.base, args.head)
    unmerged = sh("rev-list", "--count", "{}..{}".format(args.head, args.base))

    # name-status 以 base→head 方向：A = head 新增（win7-only），D = head 删除（main-only）
    rows: List[Dict] = []
    for line in sh("diff", "--name-status", args.base, args.head).splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0][0], parts[-1]
        grade = grade_file(status, path, args.base, args.head)
        raw_grade = grade
        if grade in ("real", "win7-only") and is_allowed(path, allow):
            grade = "intentional"
        rows.append({"path": path, "status": status, "cls": classify(path),
                     "grade": grade, "raw_grade": raw_grade})

    if args.write_allow:
        pats = sorted({r["path"] for r in rows if r["raw_grade"] in ("real", "win7-only")})
        header = ["# win7 必要差异允许清单（parity_report.py --allow）",
                  "# 每行一个路径或 glob；命中的 real / win7-only 文件记为 intentional，不触发 --fail-on。",
                  "# 新增条目须在 PR 中说明理由（对应 docs/win7-sync/parity.md 的批次经验）。", ""]
        pathlib.Path(args.allow).write_text("\n".join(header + pats) + "\n", encoding="utf-8")
        print("-> wrote {} entries to {}".format(len(pats), args.allow))
        for r in rows:
            if r["raw_grade"] in ("real", "win7-only"):
                r["grade"] = "intentional"

    cnt = Counter(r["grade"] for r in rows)
    cls_cnt = Counter(r["cls"] for r in rows)
    by_area = Counter()
    for r in rows:
        top = r["path"].split("/")[0]
        if r["path"].startswith("backend/tests"):
            top = "backend/tests"
        by_area[top] += 1

    total = len(rows)
    actionable = cnt["main-only"] + cnt["real"] + cnt["win7-only"]
    lines = ["# Win7/Main Parity 看板（自动）", ""]
    lines.append("- base（main）：`{}` @ `{}`  head（win7）：`{}` @ `{}`".format(
        args.base, base_sha, args.head, head_sha))
    lines.append("- merge-base：`{}`；main ahead **{}** / win7 ahead **{}**；**main 未并入 commits：{}**".format(
        merge_base[:12], ahead_main, ahead_win7, unmerged))
    lines.append("- 异动文件：**{}**（A={} B={} C={} D={}）".format(
        total, cls_cnt["A"], cls_cnt["B"], cls_cnt["C"], cls_cnt["D"]))
    lines.append("")
    lines.append("| 残差等级 | 文件数 | 含义 |")
    lines.append("|---|---:|---|")
    meaning = {
        "typing-only": "py38 typing 回写，必要差异",
        "frozen": "D 类发布/打包冻结件，永不合流",
        "intentional": "已审计的 win7 必要差异（parity-allow.txt）",
        "win7-only": "win7 独有文件（需有 importer，否则应删）",
        "main-only": "main 有 win7 无 → **漏合入**",
        "real": "实质业务差异 → **需审阅**",
    }
    for g in ["typing-only", "frozen", "intentional", "win7-only", "main-only", "real"]:
        lines.append("| {} | {} | {} |".format(g, cnt[g], meaning[g]))
    lines.append("")
    lines.append("- **需要动作的文件：{}**（main-only + real + 未登记的 win7-only）".format(actionable))
    lines.append("- 按区域：" + "、".join("{} {}".format(k, v) for k, v in by_area.most_common()))
    lines.append("")
    for g in ["main-only", "real", "win7-only"]:
        items = [r for r in rows if r["grade"] == g]
        if not items:
            continue
        lines.append("## {}（{}）".format(g, len(items)))
        for r in items[: args.max_list]:
            lines.append("- `{}` ({})".format(r["path"], r["cls"]))
        if len(items) > args.max_list:
            lines.append("- … 另 {} 个见 JSON".format(len(items) - args.max_list))
        lines.append("")
    lines.append("> 由 `scripts/win7/parity_report.py` 生成；批次进度与经验见 `parity.md`。")
    text = "\n".join(lines) + "\n"

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(
            {"base": base_sha, "head": head_sha, "unmerged": int(unmerged), "total": total,
             "grades": dict(cnt), "files": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(text)
    print("-> {}".format(out))

    fail_on = {g.strip() for g in args.fail_on.split(",") if g.strip()}
    bad = {g: cnt[g] for g in fail_on if cnt[g]}
    if bad:
        print("::error::parity 守门失败：{}".format(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
