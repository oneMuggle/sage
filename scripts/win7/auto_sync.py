#!/usr/bin/env python3
"""
auto_sync.py — main → release/win7 自动同步（Phase 3 机器人）

B3 的经验：域级落后 >100 commits 时，整体 `git merge origin/main` 比逐个
cherry-pick 更稳（一次冲突解决、一次验证）。本脚本把这条流程固化：

    1. 基于 --target 新建同步分支
    2. `git merge --no-ff --no-commit <source>`
    3. 冲突文件按 classify_diff.py 的 A/B/C/D 分类：
         D 类（发布/打包冻结件）自动取 ours（win7 侧）
         其余冲突 → 停止，输出报告（exit 2），由人接手
    4. 无冲突：对 backend/ + packages/sage-core 跑 py38_compat_rewrite（需要 libcst），
       ruff --fix I001/F811/F401 收口 typing import，去掉 CRLF 回写产生的 \\r，
       再跑 check_py38_compat.py + `ruff check backend/` 门禁（与 CI backend-py38 一致）
    5. 提交（--commit），并把报告写到 --report（markdown）+ --report-json

退出码：0 = 已同步 / 无需同步；2 = 有需人工处理的冲突；1 = 门禁失败或其它错误

用法（本地演练）：
    python scripts/win7/auto_sync.py --dry-run
用法（CI）：
    python scripts/win7/auto_sync.py --commit --branch sync/win7-main-$(date +%Y%m%d) \\
        --report sync-report.md --report-json sync-report.json

刻意只用标准库；py38 可运行（CI 里 rewrite 步骤本身需要 py3.10+，见 workflow）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import subprocess
import sys
from typing import Dict, List, Optional

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "win7"))
from classify_diff import classify  # noqa: E402

PY38_TARGETS = ["backend", "packages/sage-core"]


class SyncError(RuntimeError):
    pass


def git(*args: str, check: bool = True, capture: bool = True) -> str:
    cmd = ["git", *args]
    proc = subprocess.run(
        cmd, cwd=REPO, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    if check and proc.returncode != 0:
        raise SyncError("git {} failed ({}):\n{}".format(" ".join(args), proc.returncode, proc.stdout))
    return (proc.stdout or "").strip()


def py(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=REPO, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def conflicted_files() -> List[str]:
    out = git("diff", "--name-only", "--diff-filter=U")
    return [line for line in out.splitlines() if line.strip()]


def strip_cr(paths: List[str]) -> int:
    """py38_compat_rewrite 在 Windows 上会把 LF 文件写成 CRLF；统一还原。"""
    fixed = 0
    for rel in paths:
        p = REPO / rel
        if not p.is_file():
            continue
        data = p.read_bytes()
        if b"\r\n" in data:
            p.write_bytes(data.replace(b"\r\n", b"\n"))
            fixed += 1
    return fixed


def changed_py_files() -> List[str]:
    out = git("diff", "--name-only", "--", *PY38_TARGETS)
    staged = git("diff", "--name-only", "--cached", "--", *PY38_TARGETS)
    files = {line for line in (out + "\n" + staged).splitlines() if line.endswith(".py")}
    return sorted(files)


def render_report(rep: Dict) -> str:
    lines = ["# win7 auto-sync 报告", ""]
    lines.append("- 时间：{}".format(rep["timestamp"]))
    lines.append("- source：`{}` @ `{}`".format(rep["source"], rep["source_sha"]))
    lines.append("- target：`{}` @ `{}`".format(rep["target"], rep["target_sha"]))
    lines.append("- 分支：`{}`".format(rep["branch"]))
    lines.append("- 待并入 commits：**{}**".format(rep["commits_behind"]))
    lines.append("- 状态：**{}**".format(rep["status"]))
    lines.append("")
    if rep.get("auto_resolved"):
        lines.append("## 自动取 ours 的 D 类冲突（发布/打包冻结件）")
        lines.extend("- `{}`".format(p) for p in rep["auto_resolved"])
        lines.append("")
    if rep.get("conflicts"):
        lines.append("## 需人工处理的冲突")
        lines.append("")
        lines.append("| 文件 | 类别 | 建议 |")
        lines.append("|------|------|------|")
        hint = {
            "A": "直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接",
            "B": "垫片：优先改 backend/compat/win7，不要改业务文件",
            "C": "平台层：win7 平台实现，保留 ours 后补齐 main 新增接口",
            "D": "冻结件：应已自动 ours，若出现说明分类规则需更新",
        }
        for item in rep["conflicts"]:
            lines.append("| `{}` | {} | {} |".format(item["path"], item["cls"], hint[item["cls"]]))
        lines.append("")
        lines.append("处理步骤：`git checkout {}` → 解决冲突 → `python scripts/py38_compat_rewrite.py backend packages/sage-core` "
                     "→ `python scripts/check_py38_compat.py` → 提交。".format(rep["branch"]))
        lines.append("")
    if rep.get("py38"):
        p38 = rep["py38"]
        lines.append("## py38 门禁")
        lines.append("- rewrite 改写文件：{}（CRLF 还原 {}）".format(p38.get("rewritten", 0), p38.get("cr_fixed", 0)))
        lines.append("- check_py38_compat：{}".format("✅ 0 violations" if p38.get("ok") else "❌ 见日志"))
        lines.append("- ruff check backend/：{}".format("✅" if p38.get("ruff_ok", True) else "❌ 见日志"))
        if p38.get("log"):
            lines.append("")
            lines.append("```")
            lines.append(p38["log"][-3000:])
            lines.append("```")
        lines.append("")
    if rep.get("merged_files") is not None:
        lines.append("- 本次合并触及文件：**{}**".format(rep["merged_files"]))
    if rep.get("commit"):
        lines.append("- 同步提交：`{}`".format(rep["commit"]))
    lines.append("")
    lines.append("> 由 `scripts/win7/auto_sync.py` 生成。合并后请跑完整 pytest / vitest，"
                 "并与 `docs/win7-sync/parity.md` 中的宿主环境性失败清单对照。")
    return "\n".join(lines)


def write_reports(rep: Dict, md: Optional[str], js: Optional[str]) -> None:
    text = render_report(rep)
    print(text)
    if md:
        pathlib.Path(md).write_text(text, encoding="utf-8")
    if js:
        pathlib.Path(js).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--source", default="origin/main")
    ap.add_argument("--target", default="origin/release/win7")
    ap.add_argument("--branch", default=None, help="同步分支名（默认 sync/win7-main-YYYYMMDD）")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--commit", action="store_true", help="无冲突且门禁通过时自动提交")
    ap.add_argument("--dry-run", action="store_true", help="只做 merge 探测，最后 abort 并回到原分支")
    ap.add_argument("--skip-rewrite", action="store_true", help="跳过 py38_compat_rewrite（无 libcst 时）")
    ap.add_argument("--report", default=None)
    ap.add_argument("--report-json", default=None)
    args = ap.parse_args()

    today = _dt.date.today().strftime("%Y%m%d")
    branch = args.branch or "sync/win7-main-{}".format(today)
    rep: Dict = {
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "source": args.source, "target": args.target, "branch": branch,
        "status": "unknown", "conflicts": [], "auto_resolved": [],
    }

    if git("status", "--porcelain", "--untracked-files=no"):
        print("!! 工作区不干净，先提交或 stash。", file=sys.stderr)
        return 1
    original_ref = git("rev-parse", "--abbrev-ref", "HEAD")
    if original_ref == "HEAD":
        original_ref = git("rev-parse", "HEAD")

    if not args.no_fetch:
        git("fetch", "--prune", "origin")
    rep["source_sha"] = git("rev-parse", "--short", args.source)
    rep["target_sha"] = git("rev-parse", "--short", args.target)
    behind = git("rev-list", "--count", "{}..{}".format(args.target, args.source))
    rep["commits_behind"] = int(behind)
    if rep["commits_behind"] == 0:
        rep["status"] = "up-to-date（无需同步）"
        write_reports(rep, args.report, args.report_json)
        return 0

    # 同步分支
    if args.dry_run:
        git("checkout", "-q", "--detach", args.target)
    else:
        git("checkout", "-q", "-B", branch, args.target)

    # 注意：merge 不要覆盖 core.autocrlf —— Windows 上 autocrlf=true 检出的 CRLF 工作树
    # 在 autocrlf=false 视角会被判定为"本地已修改"，merge 直接 Aborting。
    merge = subprocess.run(
        ["git", "merge", "--no-ff", "--no-commit", args.source],
        cwd=REPO, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    conflicts = conflicted_files()

    # D 类冲突自动取 ours（发布/打包冻结件永远保持 win7 侧）
    remaining: List[Dict] = []
    for path in conflicts:
        cls = classify(path)
        if cls == "D":
            git("checkout", "--ours", "--", path)
            git("add", "--", path)
            rep["auto_resolved"].append(path)
        else:
            remaining.append({"path": path, "cls": cls})
    rep["conflicts"] = remaining

    if remaining:
        rep["status"] = "CONFLICT（{} 个文件需人工处理）".format(len(remaining))
        if args.dry_run:
            git("merge", "--abort", check=False)
            git("checkout", "-q", original_ref)
        # 非 dry-run：保留冲突状态在同步分支上，交给人
        write_reports(rep, args.report, args.report_json)
        return 2

    if merge.returncode != 0 and not conflicts:
        rep["status"] = "merge 失败：{}".format(merge.stdout[-500:])
        git("merge", "--abort", check=False)
        git("checkout", "-q", original_ref)
        write_reports(rep, args.report, args.report_json)
        return 1

    rep["merged_files"] = len([line for line in git("diff", "--name-only", "--cached").splitlines() if line])

    # py38 兼容回写 + 门禁
    p38: Dict = {"rewritten": 0, "cr_fixed": 0, "ok": False, "ruff_ok": True, "log": ""}
    if not args.skip_rewrite:
        before = set(changed_py_files())
        rw = py("scripts/py38_compat_rewrite.py", *PY38_TARGETS)
        p38["log"] += rw.stdout
        if rw.returncode != 0:
            rep["status"] = "py38_compat_rewrite 失败"
            rep["py38"] = p38
            if args.dry_run:
                git("merge", "--abort", check=False)
                git("checkout", "-q", original_ref)
            write_reports(rep, args.report, args.report_json)
            return 1
        touched = sorted(set(changed_py_files()) | before)
        p38["cr_fixed"] = strip_cr(touched)
        p38["rewritten"] = sum(1 for line in rw.stdout.splitlines() if line.strip().startswith("rewrote") or "-> rewritten" in line)
        # py38_compat_rewrite 把 `from typing import …` 插在 __future__ 之后（顶部），
        # 会触发 ruff I001（isort）/ F811（与既有 typing import 重名）。CI backend-py38
        # 的第一步就是 `ruff check backend/`，所以这里用 --fix 收口（仅 I001/F811/F401）。
        rf = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--fix", "--select", "I001,F811,F401", "--", *PY38_TARGETS],
            cwd=REPO, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        p38["log"] += "\n[ruff --fix I001,F811,F401]\n" + rf.stdout[-1500:]
        touched = sorted(set(changed_py_files()) | set(touched))
        p38["cr_fixed"] += strip_cr(touched)
        git("add", "-A", "--", *PY38_TARGETS)
    # 与 CI backend-py38 第一步一致：ruff 全量（用 backend/ruff.toml）
    rc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "backend/"],
        cwd=REPO, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    p38["ruff_ok"] = rc.returncode == 0
    if not p38["ruff_ok"]:
        p38["log"] += "\n[ruff check backend/]\n" + rc.stdout[-2000:]
    chk = py("scripts/check_py38_compat.py")
    p38["log"] += "\n" + chk.stdout
    p38["ok"] = chk.returncode == 0 and p38.get("ruff_ok", True)
    rep["py38"] = p38
    if not p38["ok"]:
        rep["status"] = "py38 门禁失败" if chk.returncode else "ruff 门禁失败（backend/ruff.toml）"
        if args.dry_run:
            git("merge", "--abort", check=False)
            git("checkout", "-q", original_ref)
        write_reports(rep, args.report, args.report_json)
        return 1

    if args.dry_run:
        rep["status"] = "DRY-RUN：可自动合并（无冲突，py38 门禁通过）"
        git("merge", "--abort", check=False)
        git("reset", "-q", "--hard")
        git("checkout", "-q", original_ref)
        write_reports(rep, args.report, args.report_json)
        return 0

    if args.commit:
        msg = (
            "chore(win7-sync): merge {src} ({sha}) → win7, {n} commits\n\n"
            "- 自动同步（scripts/win7/auto_sync.py）\n"
            "- D 类冻结件取 ours：{d}\n"
            "- py38_compat_rewrite + check_py38_compat 通过\n"
        ).format(src=args.source, sha=rep["source_sha"], n=rep["commits_behind"],
                 d=", ".join(rep["auto_resolved"]) or "无")
        git("-c", "core.autocrlf=false", "commit", "-q", "-m", msg)
        rep["commit"] = git("rev-parse", "--short", "HEAD")
        rep["status"] = "SYNCED（已提交到 {}）".format(branch)
    else:
        rep["status"] = "MERGED（未提交，工作区处于 {} 待审）".format(branch)
    write_reports(rep, args.report, args.report_json)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SyncError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
