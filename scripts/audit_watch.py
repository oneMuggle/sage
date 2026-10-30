#!/usr/bin/env python3
"""audit-watch（对标总账优化建议 3，round40）：审计门自动化前置。

对 pip-audit JSON 报告与 ``.github/dependency-audit-policy.json`` 白名单求
差，输出「未被策略覆盖的发现」清单——把"审计门被新公告打红"从 PR CI 失败
才被人发现，前置为定时 workflow 的 issue 提示。

复用 check_dependency_audit 的 pip_findings / validate_policy，保证与强制
门同一套匹配语义；本脚本只做只读分析，不修改策略。

用法::

    python scripts/audit_watch.py \\
        --pip-report "main Python 3.11 production path"=pip-audit-main.json \\
        --pip-report "Win7 LTS Python 3.8 production path"=pip-audit-py38.json \\
        --policy .github/dependency-audit-policy.json \\
        --out uncovered.txt [--json-out uncovered.json]

退出码：0 = 全部覆盖；2 = 存在未覆盖发现；1 = 输入/策略校验失败。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from check_dependency_audit import (  # noqa: E402
    Key,
    pip_findings,
    validate_policy,
)


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def uncovered_findings(
    pip_reports: list[tuple[str, Any]], policy: Any
) -> tuple[list[Key], list[Key], list[str]]:
    """返回 (未覆盖发现, 全部发现, 校验失败列表)。

    未覆盖 = 各报告 pip_findings 之并 - validate_policy 策略键集。
    每份报告的 affected_path 统一改写为调用方给定标签（round44：py38
    报告内 pip_findings 硬编码 main 标签，需按报告来源重贴）。校验失败
    列表非空表示策略文件本身或报告格式有问题（同样应触发人工介入）。
    """
    failures: list[str] = []
    policy_keys = validate_policy(policy, failures)
    pip_keys: set[Key] = set()
    for label, report in pip_reports:
        report_failures: list[str] = []
        found = (
            pip_findings(report, report_failures)
            if report is not None
            else set()
        )
        pip_keys |= {(s, p, v, a, label) for (s, p, v, a, _old) in found}
        failures.extend(report_failures)
    return (
        sorted(pip_keys - policy_keys),
        sorted(pip_keys),
        failures,
    )


def format_lines(findings: list[Key]) -> str:
    if not findings:
        return "audit-watch: 未发现未覆盖的依赖公告。\n"
    lines = ["audit-watch：以下依赖公告未被策略白名单覆盖，审计门即将打红：", ""]
    for _src, package, version, advisory, affected in findings:
        lines.append(
            f"- {package}=={version} {advisory}（{affected}）"
            f" https://osv.dev/vulnerability/{advisory}"
        )
    lines += [
        "",
        "处置：确认可达性后，在 `.github/dependency-audit-policy.json` 增补",
        "豁免条目（review_by/controls 必填），或升级到修复版本。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pip-report",
        action="append",
        required=True,
        metavar="标签=报告路径",
        help="pip-audit JSON 报告（标签=路径，可重复）",
    )
    parser.add_argument("--policy", required=True, help="审计策略 JSON 路径")
    parser.add_argument(
        "--out", help="未覆盖清单文本输出路径（缺省仅打印 stdout）"
    )
    parser.add_argument(
        "--json-out", help="未覆盖清单 JSON 输出路径（可选）"
    )
    args = parser.parse_args()

    reports: list[tuple[str, Any]] = []
    try:
        for pair in args.pip_report:
            label, sep, path = pair.partition("=")
            if not sep or not label.strip():
                print(
                    f"audit-watch: --pip-report 需为 标签=路径 形式: {pair}",
                    file=sys.stderr,
                )
                return 1
            reports.append((label.strip(), read_json(path.strip())))
        policy = read_json(args.policy)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"audit-watch: 输入读取失败: {exc}", file=sys.stderr)
        return 1

    uncovered, _all_findings, failures = uncovered_findings(reports, policy)
    for failure in failures:
        print(f"audit-watch: {failure}", file=sys.stderr)
    if failures:
        return 1

    text = format_lines(uncovered)
    print(text, end="")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    if args.json_out:
        payload = [
            {
                "package": p,
                "version": v,
                "advisory": a,
                "affected_path": path,
            }
            for _s, p, v, a, path in uncovered
        ]
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 2 if uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
