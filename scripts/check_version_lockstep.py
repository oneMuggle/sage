#!/usr/bin/env python3
"""校验 main 与 release/win7 的发布版本 lockstep。

规则来源：docs/technical/30-release-tiers.md §30.4「win7 LTS 派生」
  - win7 LTS 与 main 走完全平行的 4 档发布线；
  - **MAJOR.MINOR.PATCH 强同步**：win7 的 `X.Y.Z` 必须等于 main 的 `X.Y.Z`；
  - **tier 编号强同步**：win7 的 `alpha.N` / `beta.N` / `rc.N` 必须与 main 一致；
  - win7 tag 在 main tag 基础上加 `-win7` 后缀。
  - package-lock.json 的根 version 与 packages[''].version 必须等于 package.json。

本脚本只做**检查**，不自动打 tag —— §30.3 明确「CI 里不自动打 tag（始终人工确认）」。

用法：
    python scripts/check_version_lockstep.py
    python scripts/check_version_lockstep.py --main-ref origin/main
  python scripts/check_version_lockstep.py --main-ref worktree   # 提交前本地自检
    python scripts/check_version_lockstep.py --json
    python scripts/check_version_lockstep.py --tags            # 额外报告 tag 配对
    python scripts/check_version_lockstep.py --strict-changelog # CHANGELOG 顶端也必须配对
    python scripts/check_version_lockstep.py --strict-tags      # 未配对 tag 也算失败

退出码：0 = 一致；1 = 漂移；2 = 参数或环境错误。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

WIN7_SUFFIX = "-win7"
SEMVER_RE = re.compile(r"^(?P<base>\d+\.\d+\.\d+)(?:-(?P<tier>[0-9A-Za-z.\-]+))?$")
CHANGELOG_HEADING_RE = re.compile(r"^##\s+\[v?(?P<ver>[^\]]+)\]\s*-\s*(?P<date>\S+)", re.M)


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError("git {} 失败：{}".format(" ".join(args), proc.stderr.strip()))
    return proc.stdout


WORKTREE_REFS = (".", "worktree", "WORKTREE")


def _read_ref(ref: str, path: str) -> str:
    """ref 为 worktree 时读磁盘，否则读 git 对象。"""
    if ref in WORKTREE_REFS:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    return git("show", "{}:{}".format(ref, path))


def read_package_version(ref: str) -> str:
    raw = _read_ref(ref, "package.json")
    data = json.loads(raw)
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("{}: package.json 缺少 version 字段".format(ref))
    return version


def read_lock_versions(ref: str):
    """读 package-lock.json 的根 version 与 packages[''].version（缺失则返回 None）。"""
    try:
        raw = _read_ref(ref, "package-lock.json")
    except Exception:
        return None, None
    try:
        data = json.loads(raw)
    except ValueError:
        return None, None
    root = data.get("version")
    pkgs = data.get("packages") or {}
    inner = (pkgs.get("") or {}).get("version")
    return root, inner


def read_top_changelog_version(ref: str):
    """取 CHANGELOG 里最新的已发布版本标题（跳过 Unreleased）。"""
    raw = _read_ref(ref, "CHANGELOG.md")
    for match in CHANGELOG_HEADING_RE.finditer(raw):
        ver = match.group("ver").strip()
        if ver.lower() == "unreleased":
            continue
        return ver, match.group("date")
    return None, None


def list_tags() -> list:
    try:
        out = git("tag", "--list", "v*")
    except RuntimeError:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def parse_semver(version: str):
    match = SEMVER_RE.match(version)
    if not match:
        return None
    return match.group("base"), match.group("tier") or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 main 与 release/win7 版本 lockstep")
    parser.add_argument("--main-ref", default="HEAD", help="main 侧 git ref；传 worktree 读工作区文件（默认 HEAD）")
    parser.add_argument("--win7-ref", default="origin/release/win7", help="win7 侧 git ref")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--tags", action="store_true", help="额外报告 tag 配对情况")
    parser.add_argument("--strict-tags", action="store_true", help="未配对 tag 也判为失败")
    parser.add_argument("--strict-changelog", action="store_true", help="CHANGELOG 顶端也要求配对")
    args = parser.parse_args()

    problems = []
    warnings = []
    report = {}

    try:
        main_ver = read_package_version(args.main_ref)
        win7_ver = read_package_version(args.win7_ref)
    except (RuntimeError, ValueError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 2

    report["main"] = {"ref": args.main_ref, "version": main_ver}
    report["win7"] = {"ref": args.win7_ref, "version": win7_ver}

    # 规则 1：win7 必须带 -win7 后缀
    if not win7_ver.endswith(WIN7_SUFFIX):
        problems.append(
            "win7 版本 `{}` 缺少 `{}` 后缀".format(win7_ver, WIN7_SUFFIX)
        )
        win7_base = win7_ver
    else:
        win7_base = win7_ver[: -len(WIN7_SUFFIX)]

    if main_ver.endswith(WIN7_SUFFIX):
        problems.append("main 版本 `{}` 不应带 `-win7` 后缀".format(main_ver))

    # 规则 2：两侧版本必须逐字相等（main == win7 去掉后缀）
    if win7_base != main_ver:
        problems.append(
            "版本脱钩：main=`{}` 而 win7=`{}`（去掉后缀应为 `{}`）".format(
                main_ver, win7_ver, main_ver
            )
        )

    # 规则 3：semver 结构与 tier 编号
    main_parsed = parse_semver(main_ver)
    win7_parsed = parse_semver(win7_base)
    if main_parsed is None:
        problems.append("main 版本 `{}` 不是合法 semver".format(main_ver))
    if win7_parsed is None:
        problems.append("win7 版本 `{}` 不是合法 semver".format(win7_base))
    if main_parsed and win7_parsed:
        if main_parsed[0] != win7_parsed[0]:
            problems.append(
                "MAJOR.MINOR.PATCH 不一致：main `{}` vs win7 `{}`".format(
                    main_parsed[0], win7_parsed[0]
                )
            )
        if main_parsed[1] != win7_parsed[1]:
            problems.append(
                "tier 编号不一致：main `{}` vs win7 `{}`".format(
                    main_parsed[1], win7_parsed[1]
                )
            )
        report["base"] = main_parsed[0]
        report["tier"] = main_parsed[1]

    # 规则 3b：package-lock.json 必须与 package.json 同步
    # 背景：tests/packaging/package-version-contract.spec.ts 断言两者根版本相等，
    # 只改 package.json 会让 `npm run test:coverage` 直接失败（PR #2233 实际踩过）。
    main_lock_root, main_lock_inner = read_lock_versions(args.main_ref)
    win7_lock_root, win7_lock_inner = read_lock_versions(args.win7_ref)
    report["lock"] = {
        "main": {"root": main_lock_root, "packages_root": main_lock_inner},
        "win7": {"root": win7_lock_root, "packages_root": win7_lock_inner},
    }
    for label, root_ver, inner_ver, pkg_ver in (
        ("main", main_lock_root, main_lock_inner, main_ver),
        ("win7", win7_lock_root, win7_lock_inner, win7_ver),
    ):
        if root_ver is None:
            continue
        if root_ver != pkg_ver:
            problems.append(
                "{}: package-lock.json 根 version `{}` != package.json `{}`"
                "（tests/packaging/package-version-contract.spec.ts 会失败）".format(label, root_ver, pkg_ver)
            )
        if inner_ver is not None and inner_ver != pkg_ver:
            problems.append(
                "{}: package-lock.json packages[''].version `{}` != package.json `{}`".format(
                    label, inner_ver, pkg_ver
                )
            )

    # 规则 4（可选）：CHANGELOG 顶端版本
    try:
        main_cl, main_date = read_top_changelog_version(args.main_ref)
        win7_cl, win7_date = read_top_changelog_version(args.win7_ref)
    except RuntimeError:
        main_cl = win7_cl = None
        main_date = win7_date = None
    report["changelog"] = {
        "main": {"version": main_cl, "date": main_date},
        "win7": {"version": win7_cl, "date": win7_date},
    }
    if main_cl and win7_cl:
        main_cl_base = main_cl[:-len(WIN7_SUFFIX)] if main_cl.endswith(WIN7_SUFFIX) else main_cl
        win7_cl_base = win7_cl[:-len(WIN7_SUFFIX)] if win7_cl.endswith(WIN7_SUFFIX) else win7_cl
        if main_cl_base != win7_cl_base:
            msg = "CHANGELOG 顶端不一致：main `{}` vs win7 `{}`".format(main_cl, win7_cl)
            (problems if args.strict_changelog else warnings).append(msg)
        if main_cl_base != main_ver:
            msg = "CHANGELOG 顶端 `{}` 落后于 package.json `{}`（main）".format(main_cl, main_ver)
            (problems if args.strict_changelog else warnings).append(msg)

    # 规则 5（可选）：当前版本的 tag 配对（历史 tag 不作强校验：lts 命名与 win7 独有发布线
    # 导致大量天然未配对，逐条告警只会变成噪音）
    if args.tags or args.strict_tags:
        tags = list_tags()
        tagged = {t[1:] for t in tags}          # 去掉前缀 v
        main_tag = main_ver
        win7_tag = win7_ver
        has_main = main_tag in tagged
        has_win7 = win7_tag in tagged
        report["tags"] = {
            "main_tag": {"tag": main_tag, "exists": has_main},
            "win7_tag": {"tag": win7_tag, "exists": has_win7},
            "total": len(tagged),
        }
        if has_win7 and not has_main:
            msg = "win7 已发布 `v{}`，但 main 尚无配对的 `v{}` tag".format(win7_tag, main_tag)
            (problems if args.strict_tags else warnings).append(msg)
        if has_main and not has_win7:
            msg = "main 已发布 `v{}`，但 win7 尚无配对的 `v{}` tag".format(main_tag, win7_tag)
            (problems if args.strict_tags else warnings).append(msg)

    report["ok"] = not problems
    report["problems"] = problems
    report["warnings"] = warnings

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("main  ({})  : {}".format(args.main_ref, main_ver))
        print("win7  ({}) : {}".format(args.win7_ref, win7_ver))
        if main_cl or win7_cl:
            print("CHANGELOG 顶端 : main={} / win7={}".format(main_cl, win7_cl))
        print("")
        for msg in warnings:
            print("::warning::{}".format(msg))
        for msg in problems:
            print("::error::{}".format(msg))
        if problems:
            print("\n版本 lockstep 校验失败：{} 项".format(len(problems)))
            print("修复方式：按 §30.4 把落后一侧的 package.json / CHANGELOG 对齐到同一版本，")
            print("         win7 侧版本 = main 版本 + `-win7`（打 tag 仍需人工确认）。")
        else:
            print("版本 lockstep 校验通过。")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
