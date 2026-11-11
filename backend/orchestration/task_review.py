"""``task_review`` — 任务级复核：每个 task 实现完成后立即复核。

与 ``review.py``（aggregate 级，复核整条 lane 的聚合结果）不同，本模块
只换输入源：task goal + 实现者输出 + TDD 证据 + 验收结果；复核维度是
"这个 task 本身是否达标"，而不是"整条 lane 的汇总是否达标"。

verdict 判定规则：

1. reviewer 显式 ``VERDICT: PASS|FAIL`` 行优先；
2. 无显式 verdict 行时回落到既有 assertion 机制
   （``review.parse_assertions`` + ``review.compute_verdict``）；
3. fail-safe：显式 ``PASS`` 与高置信 ``NEGATIVE_EVIDENCE`` 冲突时判 fail。

``review`` 在函数内惰性导入——``review`` 模块级导入 ``executor``，若本
模块再模块级导入 ``review``，executor → task_review → review → executor
会形成导入环。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: reviewer 显式结论行（兼容中英文冒号）。
_VERDICT_RE = re.compile(
    r"^[ \t]*VERDICT[ \t]*[:：][ \t]*(PASS|FAIL)\b", re.IGNORECASE | re.MULTILINE
)

#: reviewer 失败原因行。
_REASON_RE = re.compile(r"^[ \t]*REASON[ \t]*[:：][ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)

_OUTPUT_FORMAT = """### 输出格式

先逐条给出 assertion，每行一条：
[FACT] <已核实的事实> (confidence: 0.0-1.0)
[HYPOTHESIS] <待验证的推断> (confidence: 0.0-1.0)
[NEGATIVE_EVIDENCE] <已检查但未通过的点> (confidence: 0.0-1.0)

最后给出结论（单独一行，必须存在）：
VERDICT: PASS
或
VERDICT: FAIL
REASON: <失败原因，一句话>"""


def _render_tdd_snapshot(snapshot: Dict[str, Any]) -> str:
    """TDD 证据快照 → 文本块。"""
    lines = ["### TDD 证据（工具层审计）"]
    lines.append(f"- 模式: {snapshot.get('mode', 'unknown')}")
    for label, key in (("测试文件", "test_files"), ("实现文件", "impl_writes")):
        items = snapshot.get(key) or []
        lines.append(f"- {label}: {len(items)}")
        for item in items:
            lines.append(f"  - {item}")
    runs = snapshot.get("test_runs") or []
    lines.append(f"- 测试运行: {len(runs)}")
    for run in runs:
        command = run.get("command", "") if isinstance(run, dict) else ""
        exit_code = run.get("exit_code") if isinstance(run, dict) else None
        lines.append(f"  - `{command}` → exit_code={exit_code}")
    lines.append(f"- red_seen: {bool(snapshot.get('red_seen'))}")
    lines.append(f"- green_seen: {bool(snapshot.get('green_seen'))}")
    lines.append(f"- TDD 合规: {bool(snapshot.get('compliant'))}")
    violations = snapshot.get("violations") or []
    if violations:
        lines.append(f"- 违规: {len(violations)}")
        for violation in violations:
            if isinstance(violation, dict):
                lines.append(f"  - {violation.get('kind')} @ {violation.get('path')}")
    return "\n".join(lines)


def _render_acceptance(report: Dict[str, Any]) -> str:
    """验收报告 → 文本块。"""
    checks = report.get("checks") or []
    lines = ["### 验收结果（acceptance checks）"]
    lines.append(f"- 全部通过: {bool(report.get('all_passed'))}")
    if not checks:
        lines.append("- 无检查项")
    for check in checks:
        if not isinstance(check, dict):
            continue
        status = "通过" if check.get("passed") else "未通过"
        if check.get("skipped"):
            status = "跳过"
        summary = check.get("summary") or ""
        lines.append(f"- {check.get('name')}: {status} — {summary}")
    return "\n".join(lines)


def build_task_review_prompt(
    goal: str,
    implementer_output: str,
    tdd_snapshot: Dict[str, Any],
    acceptance_report: Optional[Dict[str, Any]] = None,
) -> str:
    """构造 task-level review prompt。

    Args:
        goal: 本 task 的目标（``TaskPacket.objective``）。
        implementer_output: 实现者子 agent 的输出摘要。
        tdd_snapshot: ``TddGuard.snapshot()``。
        acceptance_report: ``AcceptanceReport.to_dict()``；``None`` 表示本轮
            没有跑验收。
    """
    snapshot = tdd_snapshot or {}
    is_tdd = snapshot.get("mode") == "tdd"

    parts = [
        "## 任务级复核（task-level review）",
        "",
        "### 任务目标",
        (goal or "").strip() or "（未提供目标）",
        "",
        "### 实现者输出",
        (implementer_output or "").strip() or "（无输出）",
        "",
    ]

    if is_tdd:
        parts.append(_render_tdd_snapshot(snapshot))
        parts.append("")

    if acceptance_report:
        parts.append(_render_acceptance(acceptance_report))
        parts.append("")

    dimensions = [
        "1. **Spec compliance** — 实现是否覆盖任务目标里的全部要求，" "有无可核查的证据支撑。",
    ]
    if is_tdd:
        dimensions.append(
            "2. **TDD compliance** — 是否存在 red→green 证据链"
            "（先有失败测试，再有通过测试），是否存在 TDD 顺序违规。",
        )
    dimensions.append(
        f"{len(dimensions) + 1}. **Quality** — 代码质量、边界处理、" "错误处理是否到位。",
    )

    parts.append("### 审查维度")
    parts.extend(dimensions)
    parts.append("")
    parts.append(_OUTPUT_FORMAT)
    return "\n".join(parts)


def _derive_reason(assertions: List[Any]) -> str:
    """无显式 REASON 行时的兜底原因。"""
    for assertion in assertions:
        atype = getattr(assertion, "type", None)
        if atype is not None and getattr(atype, "value", None) == "negative_evidence":
            return assertion.statement
    if not assertions:
        return "reviewer 未产出任何可解析 assertion"
    return "reviewer 判定不通过"


def parse_review_verdict(reviewer_output: str) -> Dict[str, Any]:
    """解析 reviewer 输出 → ``{"verdict", "reason", "assertions"}``。

    ``verdict`` 为 ``"pass"`` / ``"fail"``；``assertions`` 为
    ``Assertion.to_dict()`` 列表（可直接落事件）。
    """
    from backend.orchestration.review import compute_verdict, parse_assertions

    raw = reviewer_output or ""
    assertions = parse_assertions(raw)
    assertion_verdict = compute_verdict(assertions)

    verdict_match = _VERDICT_RE.search(raw)
    explicit = verdict_match.group(1).lower() if verdict_match else None

    reason_match = _REASON_RE.search(raw)
    reason = reason_match.group(1).strip() if reason_match else ""

    if explicit is None:
        verdict = assertion_verdict
        if verdict == "fail" and not reason:
            reason = _derive_reason(assertions)
    else:
        verdict = explicit
        if explicit == "pass" and assertion_verdict == "fail":
            # fail-safe：reviewer 自称通过，但存在高置信负向证据 → 判不通过。
            verdict = "fail"
        if verdict == "fail" and not reason:
            reason = _derive_reason(assertions)

    return {
        "verdict": verdict,
        "reason": reason,
        "assertions": [a.to_dict() for a in assertions],
    }
