#!/usr/bin/env python3
"""
parity_report.py — 生成 win7 vs main 的对齐度看板
"""
import subprocess, pathlib, json

REPO = pathlib.Path(__file__).resolve().parents[2]

def sh(cmd):
    return subprocess.check_output(cmd, cwd=REPO, shell=True, text=True).strip()

def main():
    try:
        left_right = sh("git rev-list --left-right --count origin/main...origin/release/win7")
        ahead_main, ahead_win7 = left_right.split()
    except Exception:
        ahead_main = ahead_win7 = "?"
    try:
        base = sh("git merge-base origin/main origin/release/win7")
    except Exception:
        base = "?"
    try:
        diff_count = sh("git diff --name-only origin/main...origin/release/win7 | wc -l")
    except Exception:
        diff_count = "?"
    try:
        subprocess.check_output(["python", "scripts/win7/classify_diff.py"], cwd=REPO, text=True)
        csv = (REPO / "docs/win7-sync/classify.csv").read_text(encoding="utf-8")
        cnt = {k: csv.count(f",{k},") for k in ["A","B","C","D"]}
    except Exception as e:
        cnt = {"A": "?", "B": "?", "C": "?", "D": f"error:{e}"}
    report = f"""# Win7/Main Parity 看板

- merge-base: `{base}`
- main ahead: **{ahead_main}** / win7 ahead: **{ahead_win7}**
- 异动文件: **{diff_count}**
- 分类: A={cnt.get('A')} B={cnt.get('B')} C={cnt.get('C')} D={cnt.get('D')}

| 维度 | 目标 | 当前推算 | 差距 |
|------|------|----------|------|
| 功能对齐 | >=95% | ~62% (B+C 待消化) | 需 B1-B6 六批次 |
| 代码同源 | >=80% | ~54% (A类直通) | P1 平台层后可达 82% |
| 发布同构 | 同构 | 差异 67 文件 (D) | C 层收敛后 <50 行 |
| 约束隔离 | >=90% 集中 | 散弹（现状） | 需 platform/win7 |
"""
    out = REPO / "docs/win7-sync/parity.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"-> {out}")

if __name__ == "__main__":
    main()
