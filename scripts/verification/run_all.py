#!/usr/bin/env python3
"""
run_all.py — Sage 验证映射自动化运行器

运行所有（或指定）g00X 验证映射对应的 pytest 测试，解析结果并输出摘要。

用法:
    python scripts/verification/run_all.py            # 运行所有 g00X
    python scripts/verification/run_all.py g001       # 只运行 g001
    python scripts/verification/run_all.py g001 g003  # 运行 g001 + g003

退出码:
    0 — 所有测试通过（或没有测试目录时跳过）
    1 — 至少一个 g00X 有失败测试
    2 — 脚本自身错误（环境、参数等）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# 常量与路径
# ---------------------------------------------------------------------------

# 项目根目录 (scripts/verification/ -> ../../..)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
VERIFICATION_DIR: Path = PROJECT_ROOT / "docs" / "verification"
TESTS_VERIFICATION_DIR: Path = PROJECT_ROOT / "tests" / "verification"
INTEGRATION_DIR: Path = PROJECT_ROOT / "tests" / "integration"
RESULTS_JSON: Path = PROJECT_ROOT / "data" / "verification_results.json"

# Python 解释器: 优先使用 conda sage-backend 环境
CONDA_PYTHON: str = "/home/fz/anaconda3/envs/sage-backend/bin/python"
FALLBACK_PYTHON: str = sys.executable

# 所有已知验证映射 ID
KNOWN_MAPS: list[str] = [
    "g001", "g002", "g003", "g004",
    "g005", "g006", "g007", "g008", "g009",
]

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class MapResult:
    """单个 g00X 验证映射的运行结果。"""
    map_id: str
    status: str  # "passed" | "failed" | "no_tests" | "skipped" | "error"
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    coverage: float | None = None  # 百分比 (0-100), 无覆盖率数据时为 None
    duration: float = 0.0  # 秒
    failures: list[dict[str, str]] = field(default_factory=list)
    pytest_output: str = ""


@dataclass
class RunSummary:
    """所有 g00X 的运行汇总。"""
    timestamp: str
    python: str
    total_maps: int = 0
    maps_passed: int = 0
    maps_failed: int = 0
    maps_no_tests: int = 0
    maps_error: int = 0
    overall_passed: int = 0
    overall_failed: int = 0
    overall_errors: int = 0
    overall_skipped: int = 0
    total_duration: float = 0.0
    average_coverage: float | None = None
    results: list[MapResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def resolve_python() -> str:
    """解析可用的 Python 解释器。"""
    if os.path.isfile(CONDA_PYTHON) and os.access(CONDA_PYTHON, os.X_OK):
        return CONDA_PYTHON
    return FALLBACK_PYTHON


def discover_test_dirs(map_id: str) -> list[Path]:
    """
    查找某 g00X 对应的测试目录/文件。

    搜索顺序:
      1. tests/verification/g0XX/
      2. tests/integration/g0XX/
      3. backend/tests/ 下按子系统名匹配的测试文件（回退）
    """
    candidates: list[Path] = []

    verification_path = TESTS_VERIFICATION_DIR / map_id
    if verification_path.is_dir():
        candidates.append(verification_path)

    integration_path = INTEGRATION_DIR / map_id
    if integration_path.is_dir():
        candidates.append(integration_path)

    # 回退: 在 tests/ 下查找包含 map_id 关键字的测试文件
    tests_dir = PROJECT_ROOT / "tests"
    if tests_dir.is_dir():
        for py_file in tests_dir.rglob(f"*{map_id}*"):
            if py_file.is_file() and py_file.name.startswith("test_"):
                candidates.append(py_file)

    # 回退: 按子系统名映射到已知测试文件（backend/tests/）
    subsystem_test_map: dict[str, list[str]] = {
        "g001": [
            "test_memory_working", "test_memory_episodic",
            "test_memory_semantic", "test_memory_manager",
            "test_memory_consolidation", "test_memory_tool",
            "test_memory_storage_adapter",
        ],
        "g002": [
            "test_calculator", "test_terminal", "test_file_tool",
            "test_web_tool", "test_tool_registry", "test_memory_tool",
        ],
        "g003": [
            "test_skill_registry", "test_skill_base",
            "test_skill_md_loader", "test_skill_md_frontmatter",
            "test_skill_md_validation",
        ],
        "g004": [
            "test_sage_agent", "test_agent_orchestrator",
            "test_chat_service",
        ],
    }

    if map_id in subsystem_test_map and not candidates:
        for sub_dir_name in ("unit", "integration"):
            sub_dir = PROJECT_ROOT / "backend" / "tests" / sub_dir_name
            if sub_dir.is_dir():
                for test_name in subsystem_test_map[map_id]:
                    test_file = sub_dir / f"{test_name}.py"
                    if test_file.is_file():
                        candidates.append(test_file)

    return candidates


def parse_pytest_output(output: str) -> dict[str, Any]:
    """
    从 pytest 标准输出中解析测试统计。

    返回字典:
      {
        "total": int,
        "passed": int,
        "failed": int,
        "errors": int,
        "skipped": int,
        "duration": float,
        "coverage": float | None,
        "failures": [{"name": str, "message": str}]
      }
    """
    result: dict[str, Any] = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration": 0.0,
        "coverage": None,
        "failures": [],
    }

    # pytest 摘要行示例:
    #   "= 5 passed in 1.23s ="
    #   "= 3 passed, 2 failed, 1 error in 4.56s ="
    summary_pattern = re.compile(
        r"=\s+"
        r"(?P<counts>.+?)"
        r"\s+in\s+(?P<duration>[\d.]+)s"
        r"\s*="
    )
    for line in output.splitlines():
        m = summary_pattern.search(line)
        if not m:
            continue

        counts_str = m.group("counts")
        duration = float(m.group("duration"))
        result["duration"] = duration

        # 解析各类计数
        count_pattern = re.compile(r"(\d+)\s+(passed|failed|error|skipped)")
        for cm in count_pattern.finditer(counts_str):
            count = int(cm.group(1))
            kind = cm.group(2)
            if kind == "passed":
                result["passed"] = count
            elif kind == "failed":
                result["failed"] = count
            elif kind == "error":
                result["errors"] = count
            elif kind == "skipped":
                result["skipped"] = count

        if "no tests ran" in counts_str:
            result["total"] = 0
        else:
            result["total"] = (
                result["passed"] + result["failed"]
                + result["errors"] + result["skipped"]
            )
        break

    # 解析 pytest-cov 的 TOTAL 行（示例: "TOTAL    45    3    93%"）
    cov_pattern = re.compile(r"TOTAL\s+\d+\s+\d+\s+(\d+)%")
    for line in output.splitlines():
        cm = cov_pattern.search(line)
        if cm:
            result["coverage"] = float(cm.group(1))
            break

    # 解析 FAILURES 段中每个失败测试的名称和首条错误信息
    failure_header = re.compile(r"^-+\s*_+\s+(.*?)\s*_+-+$")
    current_failure: dict[str, str] | None = None
    for line in output.splitlines():
        fm = failure_header.match(line)
        if fm:
            if current_failure is not None:
                result["failures"].append(current_failure)
            current_failure = {"name": fm.group(1).strip(), "message": ""}
        elif current_failure is not None:
            if line.startswith("="):
                result["failures"].append(current_failure)
                current_failure = None
            elif line.startswith("E "):
                current_failure["message"] = line[2:].strip()
    if current_failure is not None:
        result["failures"].append(current_failure)

    return result


def run_pytest_for_map(
    map_id: str,
    test_paths: Sequence[Path],
    python: str,
) -> MapResult:
    """
    对单个 g00X 运行 pytest，返回 MapResult。
    """
    result = MapResult(map_id=map_id, status="no_tests")

    if not test_paths:
        return result

    # 构建 pytest 命令
    cmd: list[str] = [
        python, "-m", "pytest",
        "-v",
        "--tb=short",
        "--no-header",
    ]

    # 添加覆盖率收集（仅对已知子系统路径）
    coverage_targets: dict[str, str] = {
        "g001": "backend/memory",
        "g002": "backend/tools",
        "g003": "backend/skills",
        "g004": "backend/core/legacy",
    }
    if map_id in coverage_targets:
        cmd.extend([
            f"--cov={coverage_targets[map_id]}",
            "--cov-report=term-missing",
            "--no-cov-on-fail",
        ])

    # 添加测试路径
    cmd.extend(str(p) for p in test_paths)

    try:
        start = time.perf_counter()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 分钟超时
            cwd=str(PROJECT_ROOT),
            env={
                **os.environ,
                "PYTHONPATH": str(PROJECT_ROOT),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        elapsed = time.perf_counter() - start

        parsed = parse_pytest_output(proc.stdout + proc.stderr)

        result.total = parsed["total"]
        result.passed = parsed["passed"]
        result.failed = parsed["failed"]
        result.errors = parsed["errors"]
        result.skipped = parsed["skipped"]
        result.duration = parsed.get("duration", elapsed)
        result.coverage = parsed.get("coverage")
        result.failures = parsed.get("failures", [])
        result.pytest_output = proc.stdout + proc.stderr

        # 判定状态
        if result.total == 0:
            result.status = "no_tests"
        elif result.failed > 0 or result.errors > 0:
            result.status = "failed"
        else:
            result.status = "passed"

    except subprocess.TimeoutExpired:
        result.status = "error"
        result.errors = 1
        result.pytest_output = "pytest 超时 (300s)"
    except Exception as exc:
        result.status = "error"
        result.errors = 1
        result.pytest_output = f"运行 pytest 时出错: {exc}"

    return result


def print_progress(map_id: str, status: str, detail: str = "") -> None:
    """打印单条运行进度。"""
    icons = {
        "passed": "✅",
        "failed": "❌",
        "no_tests": "⚠️ ",
        "skipped": "⏭️ ",
        "error": "💥",
    }
    icon = icons.get(status, "❓")
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon} {map_id}: {status}{suffix}")


def print_summary(summary: RunSummary) -> None:
    """打印运行摘要表格。"""
    print()
    print("=" * 70)
    print("Sage 验证运行摘要")
    print("=" * 70)
    print()

    # 总览表头
    header = (
        f"{'验证地图':<12} {'状态':<12} {'测试数':>6} {'通过':>6} "
        f"{'失败':>6} {'覆盖率':>8} {'耗时':>8}"
    )
    print(header)
    print("-" * 70)

    for r in summary.results:
        cov_str = f"{r.coverage:.0f}%" if r.coverage is not None else "-"
        status_display = {
            "passed": "✅ 通过",
            "failed": "❌ 失败",
            "no_tests": "⚠️  无测试",
            "skipped": "⏭️  跳过",
            "error": "💥 错误",
        }.get(r.status, r.status)

        print(
            f"{r.map_id:<12} {status_display:<12} {r.total:>6} "
            f"{r.passed:>6} {r.failed + r.errors:>6} "
            f"{cov_str:>8} {r.duration:>7.1f}s"
        )

    print("-" * 70)

    # 统计汇总
    cov_values = [r.coverage for r in summary.results if r.coverage is not None]
    avg_cov = sum(cov_values) / len(cov_values) if cov_values else None
    summary.average_coverage = avg_cov

    print()
    total_tests = (
        summary.overall_passed + summary.overall_failed
        + summary.overall_errors + summary.overall_skipped
    )
    print(f"总测试数: {total_tests}")
    print(
        f"通过: {summary.overall_passed}  "
        f"失败: {summary.overall_failed}  "
        f"错误: {summary.overall_errors}  "
        f"跳过: {summary.overall_skipped}"
    )
    print(f"耗时: {summary.total_duration:.1f}s")
    if avg_cov is not None:
        print(f"平均覆盖率: {avg_cov:.1f}%")

    # 失败详情
    failed_results = [r for r in summary.results if r.status == "failed"]
    if failed_results:
        print()
        print("失败详情:")
        print("-" * 70)
        for r in failed_results:
            for f in r.failures:
                print(f"  [{r.map_id}] {f.get('name', '未知测试')}")
                msg = f.get("message", "")
                if msg:
                    for line in msg.splitlines()[:5]:
                        print(f"    {line}")
        print()

    print("=" * 70)

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run_verification(
    map_ids: Sequence[str],
    save_results: bool = True,
) -> RunSummary:
    """
    运行指定 g00X 验证映射的测试，返回汇总结果。

    Args:
        map_ids: 要运行的映射 ID 列表
        save_results: 是否将结果保存到 JSON 文件

    Returns:
        RunSummary 包含所有映射的运行结果
    """
    python = resolve_python()
    timestamp = datetime.now(timezone.utc).isoformat()

    summary = RunSummary(
        timestamp=timestamp,
        python=python,
        total_maps=len(map_ids),
    )

    print("Sage 验证运行器")
    print(f"Python: {python}")
    print(f"时间: {timestamp}")
    print(f"目标: {', '.join(map_ids)}")
    print()

    for map_id in map_ids:
        print(f"运行 {map_id} ...")
        test_dirs = discover_test_dirs(map_id)

        if not test_dirs:
            result = MapResult(map_id=map_id, status="no_tests")
            print_progress(map_id, "no_tests", "未找到测试目录")
        else:
            result = run_pytest_for_map(map_id, test_dirs, python)
            cov_detail = f"{result.coverage:.0f}%" if result.coverage else "-"
            print_progress(
                map_id,
                result.status,
                (
                    f"{result.passed}/{result.total} 通过, "
                    f"覆盖率 {cov_detail}"
                ),
            )

        summary.results.append(result)
        summary.overall_passed += result.passed
        summary.overall_failed += result.failed
        summary.overall_errors += result.errors
        summary.overall_skipped += result.skipped
        summary.total_duration += result.duration

        if result.status == "passed":
            summary.maps_passed += 1
        elif result.status == "failed":
            summary.maps_failed += 1
        elif result.status == "error":
            summary.maps_error += 1
        elif result.status == "no_tests":
            summary.maps_no_tests += 1

    print_summary(summary)

    # 保存结果到 JSON（供 generate_report.py 读取）
    if save_results:
        try:
            RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
            with open(RESULTS_JSON, "w", encoding="utf-8") as f:
                json.dump(summary.to_dict(), f, ensure_ascii=False, indent=2)
            print(f"\n结果已保存: {RESULTS_JSON}")
        except OSError as exc:
            print(f"\n警告: 无法保存结果文件 — {exc}", file=sys.stderr)

    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """
    CLI 入口。

    Args:
        argv: 命令行参数（默认 sys.argv[1:]）

    Returns:
        退出码 (0=通过, 1=有失败, 2=脚本错误)
    """
    parser = argparse.ArgumentParser(
        description="Sage 验证映射自动化运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s              # 运行所有验证映射\n"
            "  %(prog)s g001         # 只运行 g001\n"
            "  %(prog)s g001 g003    # 运行 g001 + g003\n"
        ),
    )
    parser.add_argument(
        "maps",
        nargs="*",
        help="要运行的验证映射 ID（如 g001 g002），不指定则运行全部",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="不保存结果到 JSON 文件",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_maps",
        help="列出所有已知验证映射并退出",
    )

    args = parser.parse_args(argv)

    if args.list_maps:
        print("已知验证映射:")
        for m in KNOWN_MAPS:
            docs = list(VERIFICATION_DIR.glob(f"{m}-*.md"))
            doc_name = docs[0].stem if docs else "无文档"
            has_tests = bool(discover_test_dirs(m))
            test_icon = "✅" if has_tests else "⚠️ "
            print(f"  {m}  [{doc_name}]  测试: {test_icon}")
        return 0

    # 确定要运行的映射
    if args.maps:
        for map_id in args.maps:
            if map_id not in KNOWN_MAPS:
                print(
                    f"错误: 未知的验证映射 '{map_id}'。"
                    f"已知: {', '.join(KNOWN_MAPS)}",
                    file=sys.stderr,
                )
                return 2
        map_ids = args.maps
    else:
        # 运行所有有文档的映射
        map_ids = [
            m for m in KNOWN_MAPS
            if list(VERIFICATION_DIR.glob(f"{m}-*.md"))
        ]

    if not map_ids:
        print("未找到任何验证映射文档。")
        return 2

    summary = run_verification(map_ids, save_results=not args.no_save)

    # 退出码: 0=全部通过或无测试, 1=有失败
    if summary.overall_failed > 0 or summary.maps_error > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
