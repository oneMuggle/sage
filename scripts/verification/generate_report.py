#!/usr/bin/env python3
"""
generate_report.py — Sage 验证报告生成器

从 JSON 结果文件读取（或重新运行测试），生成人类可读的验证报告。

支持三种输出格式:
    markdown (默认) — docs/verification-report.md
    json            — docs/verification-report.json
    html            — docs/verification-report.html

用法:
    python scripts/verification/generate_report.py
    python scripts/verification/generate_report.py --format json
    python scripts/verification/generate_report.py --rerun
    python scripts/verification/generate_report.py --input data/other_results.json

退出码:
    0 — 报告生成成功
    1 — 报告生成失败
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# 常量与路径
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT: Path = PROJECT_ROOT / "data" / "verification_results.json"
DEFAULT_OUTPUT_DIR: Path = PROJECT_ROOT / "docs"

# 验证映射 ID 到中文名称的映射
MAP_NAMES: dict[str, str] = {
    "g001": "记忆系统",
    "g002": "工具执行",
    "g003": "技能生命周期",
    "g004": "Agent 编排",
    "g005": "前端状态",
    "g006": "API 契约",
    "g007": "数据持久化",
    "g008": "安全边界",
    "g009": "性能 SLA",
}

# 状态显示映射
STATUS_ICONS: dict[str, str] = {
    "passed": "✅",
    "failed": "❌",
    "no_tests": "⚠️",
    "skipped": "⏭️",
    "error": "💥",
}

STATUS_LABELS: dict[str, str] = {
    "passed": "通过",
    "failed": "失败",
    "no_tests": "无测试",
    "skipped": "跳过",
    "error": "错误",
}

# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------


def load_results(input_path: Path) -> dict[str, Any]:
    """
    从 JSON 文件加载验证结果。

    Args:
        input_path: JSON 结果文件路径

    Returns:
        解析后的字典

    Raises:
        FileNotFoundError: 文件不存在
        json.JSONDecodeError: 文件格式无效
    """
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)


def rerun_and_load() -> dict[str, Any]:
    """
    重新运行所有验证测试并返回结果字典。

    Returns:
        RunSummary.to_dict() 格式的字典
    """
    # 延迟导入避免循环依赖 — run_all 在同目录
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    from run_all import run_verification, KNOWN_MAPS  # noqa: E402

    ver_dir = PROJECT_ROOT / "docs" / "verification"
    map_ids = [
        m for m in KNOWN_MAPS
        if list(ver_dir.glob(f"{m}-*.md"))
    ]

    summary = run_verification(map_ids, save_results=False)
    return summary.to_dict()

# ---------------------------------------------------------------------------
# Markdown 报告生成
# ---------------------------------------------------------------------------


def generate_markdown(data: dict[str, Any]) -> str:
    """
    生成 Markdown 格式的验证报告。

    Args:
        data: 验证结果字典

    Returns:
        Markdown 格式的字符串
    """
    timestamp = data.get("timestamp", datetime.now(timezone.utc).isoformat())
    python_path = data.get("python", "unknown")
    results = data.get("results", [])

    # 计算汇总统计
    total_passed = data.get("overall_passed", 0)
    total_failed = data.get("overall_failed", 0)
    total_errors = data.get("overall_errors", 0)
    total_skipped = data.get("overall_skipped", 0)
    total_duration = data.get("total_duration", 0.0)
    avg_coverage = data.get("average_coverage")
    total_tests = total_passed + total_failed + total_errors + total_skipped

    # 尝试解析时间戳为可读格式
    try:
        dt = datetime.fromisoformat(timestamp)
        readable_time = dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        readable_time = timestamp

    lines: list[str] = []
    lines.append("# Sage 验证报告\n")
    lines.append(f"**生成时间**: {readable_time}  ")
    lines.append(f"**Python**: `{python_path}`  ")
    lines.append(f"**总耗时**: {total_duration:.1f}s\n")

    # 总体状态判定
    if total_failed == 0 and total_errors == 0:
        overall_status = "✅ 所有验证通过"
    elif total_tests == 0:
        overall_status = "⚠️ 未运行任何测试"
    else:
        overall_status = f"❌ 存在 {total_failed + total_errors} 个失败/错误"
    lines.append(f"**总体状态**: {overall_status}\n")

    # 概览表格
    lines.append("## 概览\n")
    lines.append(
        "| 验证地图 | 名称 | 状态 | 测试数 | 通过 | 失败 | 覆盖率 | 耗时 |"
    )
    lines.append(
        "|----------|------|------|--------|------|------|--------|------|"
    )

    for r in results:
        map_id = r.get("map_id", "???")
        map_name = MAP_NAMES.get(map_id, "未知")
        status = r.get("status", "unknown")
        icon = STATUS_ICONS.get(status, "❓")
        label = STATUS_LABELS.get(status, status)
        total = r.get("total", 0)
        passed = r.get("passed", 0)
        failed = r.get("failed", 0) + r.get("errors", 0)
        coverage = r.get("coverage")
        cov_str = f"{coverage:.0f}%" if coverage is not None else "-"
        duration = r.get("duration", 0.0)

        lines.append(
            f"| {map_id} | {map_name} | {icon} {label} | "
            f"{total} | {passed} | {failed} | "
            f"{cov_str} | {duration:.1f}s |"
        )

    lines.append("")

    # 统计部分
    lines.append("## 统计\n")
    lines.append(f"- **总测试数**: {total_tests}")
    lines.append(f"- **通过数**: {total_passed}")
    lines.append(f"- **失败数**: {total_failed}")
    lines.append(f"- **错误数**: {total_errors}")
    lines.append(f"- **跳过数**: {total_skipped}")
    if avg_coverage is not None:
        lines.append(f"- **平均覆盖率**: {avg_coverage:.1f}%")
    lines.append("")

    # 覆盖率明细
    covered_results = [r for r in results if r.get("coverage") is not None]
    if covered_results:
        lines.append("### 覆盖率明细\n")
        lines.append("| 验证地图 | 名称 | 覆盖率 |")
        lines.append("|----------|------|--------|")
        for r in covered_results:
            map_id = r.get("map_id", "???")
            map_name = MAP_NAMES.get(map_id, "未知")
            cov = r.get("coverage", 0.0)
            cov_bar = "🟢" if cov >= 80 else "🟡" if cov >= 60 else "🔴"
            lines.append(f"| {map_id} | {map_name} | {cov_bar} {cov:.0f}% |")
        lines.append("")

    # 失败详情
    failed_results = [
        r for r in results if r.get("status") in ("failed", "error")
    ]
    if failed_results:
        lines.append("## 失败详情\n")
        for r in failed_results:
            map_id = r.get("map_id", "???")
            map_name = MAP_NAMES.get(map_id, "未知")
            lines.append(f"### {map_id}: {map_name}\n")

            failures = r.get("failures", [])
            if failures:
                for f in failures:
                    name = f.get("name", "未知测试")
                    message = f.get("message", "")
                    lines.append(f"**测试**: `{name}`\n")
                    if message:
                        lines.append("```")
                        lines.append(message)
                        lines.append("```\n")
            else:
                # 没有解析到具体失败，输出 pytest 输出的最后几行
                pytest_output = r.get("pytest_output", "")
                if pytest_output:
                    tail_lines = pytest_output.strip().splitlines()[-20:]
                    lines.append("```")
                    lines.extend(tail_lines)
                    lines.append("```\n")

    # 无测试的映射
    no_test_results = [r for r in results if r.get("status") == "no_tests"]
    if no_test_results:
        lines.append("## 待验证映射\n")
        lines.append("以下映射尚无对应的验证测试:\n")
        for r in no_test_results:
            map_id = r.get("map_id", "???")
            map_name = MAP_NAMES.get(map_id, "未知")
            lines.append(f"- **{map_id}**: {map_name}")
        lines.append("")

    # 页脚
    lines.append("---\n")
    lines.append(
        f"*此报告由 `scripts/verification/generate_report.py` "
        f"自动生成于 {readable_time}。*"
    )

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# JSON 报告生成
# ---------------------------------------------------------------------------


def generate_json(data: dict[str, Any]) -> str:
    """
    生成 JSON 格式的验证报告。

    在原始结果基础上增加报告元数据。

    Args:
        data: 验证结果字典

    Returns:
        JSON 格式的字符串
    """
    report = {
        "report_type": "verification",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/verification/generate_report.py",
        "data": data,
        "map_names": MAP_NAMES,
    }
    return json.dumps(report, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# HTML 报告生成
# ---------------------------------------------------------------------------


def generate_html(data: dict[str, Any]) -> str:
    """
    生成 HTML 格式的验证报告。

    Args:
        data: 验证结果字典

    Returns:
        HTML 格式的字符串
    """
    timestamp = data.get("timestamp", datetime.now(timezone.utc).isoformat())
    python_path = data.get("python", "unknown")
    results = data.get("results", [])

    total_passed = data.get("overall_passed", 0)
    total_failed = data.get("overall_failed", 0)
    total_errors = data.get("overall_errors", 0)
    total_skipped = data.get("overall_skipped", 0)
    total_duration = data.get("total_duration", 0.0)
    avg_coverage = data.get("average_coverage")
    total_tests = total_passed + total_failed + total_errors + total_skipped

    try:
        dt = datetime.fromisoformat(timestamp)
        readable_time = dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        readable_time = timestamp

    # 总体状态
    if total_failed == 0 and total_errors == 0:
        overall_status = "✅ 所有验证通过"
        status_class = "status-passed"
    elif total_tests == 0:
        overall_status = "⚠️ 未运行任何测试"
        status_class = "status-no-tests"
    else:
        overall_status = f"❌ 存在 {total_failed + total_errors} 个失败/错误"
        status_class = "status-failed"

    # 构建表格行
    table_rows: list[str] = []
    for r in results:
        map_id = html_mod.escape(r.get("map_id", "???"))
        map_name = html_mod.escape(MAP_NAMES.get(r.get("map_id", ""), "未知"))
        status = r.get("status", "unknown")
        icon = STATUS_ICONS.get(status, "❓")
        label = STATUS_LABELS.get(status, status)
        total = r.get("total", 0)
        passed = r.get("passed", 0)
        failed = r.get("failed", 0) + r.get("errors", 0)
        coverage = r.get("coverage")
        cov_str = f"{coverage:.0f}%" if coverage is not None else "-"
        duration = r.get("duration", 0.0)

        row_class = {
            "passed": "row-passed",
            "failed": "row-failed",
            "error": "row-failed",
            "no_tests": "row-no-tests",
        }.get(status, "")

        table_rows.append(
            f'<tr class="{row_class}">'
            f"<td>{map_id}</td>"
            f"<td>{map_name}</td>"
            f"<td>{icon} {label}</td>"
            f"<td>{total}</td>"
            f"<td>{passed}</td>"
            f"<td>{failed}</td>"
            f"<td>{cov_str}</td>"
            f"<td>{duration:.1f}s</td>"
            f"</tr>"
        )

    rows_html = "\n".join(table_rows)

    # 覆盖率明细
    coverage_rows: list[str] = []
    for r in results:
        cov = r.get("coverage")
        if cov is None:
            continue
        map_id = html_mod.escape(r.get("map_id", "???"))
        map_name = html_mod.escape(MAP_NAMES.get(r.get("map_id", ""), "未知"))
        bar_class = (
            "cov-high" if cov >= 80
            else "cov-mid" if cov >= 60
            else "cov-low"
        )
        coverage_rows.append(
            f'<tr><td>{map_id}</td><td>{map_name}</td>'
            f'<td><span class="{bar_class}">{cov:.0f}%</span></td></tr>'
        )
    coverage_html = "\n".join(coverage_rows)

    # 失败详情
    failure_sections: list[str] = []
    for r in results:
        if r.get("status") not in ("failed", "error"):
            continue
        map_id = html_mod.escape(r.get("map_id", "???"))
        map_name = html_mod.escape(MAP_NAMES.get(r.get("map_id", ""), "未知"))
        failures = r.get("failures", [])

        if failures:
            items = []
            for f in failures:
                name = html_mod.escape(f.get("name", "未知测试"))
                msg = html_mod.escape(f.get("message", ""))
                items.append(
                    f"<li><code>{name}</code>"
                    + (f"<pre>{msg}</pre>" if msg else "")
                    + "</li>"
                )
            failure_sections.append(
                f"<h3>{map_id}: {map_name}</h3><ul>{''.join(items)}</ul>"
            )
        else:
            output = html_mod.escape(r.get("pytest_output", ""))
            tail = "\n".join(output.splitlines()[-15:])
            failure_sections.append(
                f"<h3>{map_id}: {map_name}</h3>"
                f"<pre>{tail}</pre>"
            )
    failures_html = "\n".join(failure_sections)

    # 组装 HTML
    coverage_section = (
        f"""<h2>覆盖率明细</h2>
<table>
<thead><tr><th>验证地图</th><th>名称</th><th>覆盖率</th></tr></thead>
<tbody>
{coverage_html}
</tbody>
</table>"""
        if coverage_html
        else ""
    )

    failures_section = (
        f"""<h2>失败详情</h2>
{failures_html}"""
        if failures_html
        else ""
    )

    avg_cov_li = (
        f"<li><strong>平均覆盖率</strong>: {avg_coverage:.1f}%</li>"
        if avg_coverage is not None
        else ""
    )

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sage 验证报告</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 960px; margin: 0 auto; padding: 2rem; color: #333;
  }}
  h1 {{ border-bottom: 2px solid #eee; padding-bottom: 0.5rem; }}
  h2 {{ margin-top: 2rem; color: #555; }}
  .meta {{ color: #666; margin-bottom: 1rem; }}
  .{status_class} {{ font-weight: bold; font-size: 1.1em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  .row-passed {{ background: #f0fff0; }}
  .row-failed {{ background: #fff0f0; }}
  .row-no-tests {{ background: #fffde0; }}
  .cov-high {{ color: #16a34a; font-weight: bold; }}
  .cov-mid {{ color: #ca8a04; font-weight: bold; }}
  .cov-low {{ color: #dc2626; font-weight: bold; }}
  pre {{
    background: #f8f8f8; padding: 1rem; border-radius: 4px;
    overflow-x: auto; font-size: 0.85em;
  }}
  ul {{ padding-left: 1.5rem; }}
  footer {{
    margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #eee;
    font-size: 0.85em; color: #999;
  }}
</style>
</head>
<body>
<h1>Sage 验证报告</h1>
<div class="meta">
  <p><strong>生成时间</strong>: {html_mod.escape(readable_time)}<br>
  <strong>Python</strong>: <code>{html_mod.escape(python_path)}</code><br>
  <strong>总耗时</strong>: {total_duration:.1f}s</p>
  <p class="{status_class}">{overall_status}</p>
</div>

<h2>概览</h2>
<table>
<thead>
<tr><th>验证地图</th><th>名称</th><th>状态</th><th>测试数</th>
    <th>通过</th><th>失败</th><th>覆盖率</th><th>耗时</th></tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

<h2>统计</h2>
<ul>
  <li><strong>总测试数</strong>: {total_tests}</li>
  <li><strong>通过数</strong>: {total_passed}</li>
  <li><strong>失败数</strong>: {total_failed}</li>
  <li><strong>错误数</strong>: {total_errors}</li>
  <li><strong>跳过数</strong>: {total_skipped}</li>
  {avg_cov_li}
</ul>

{coverage_section}

{failures_section}

<footer>
  此报告由 <code>scripts/verification/generate_report.py</code>
  自动生成于 {html_mod.escape(readable_time)}。
</footer>
</body>
</html>"""

    return html_content

# ---------------------------------------------------------------------------
# 报告写入
# ---------------------------------------------------------------------------

FORMAT_EXTENSIONS: dict[str, str] = {
    "markdown": "verification-report.md",
    "json": "verification-report.json",
    "html": "verification-report.html",
}

FORMAT_GENERATORS: dict[str, Any] = {
    "markdown": generate_markdown,
    "json": generate_json,
    "html": generate_html,
}


def write_report(
    content: str,
    fmt: str,
    output_dir: Path,
) -> Path:
    """
    将报告内容写入文件。

    Args:
        content: 报告文本内容
        fmt: 输出格式 (markdown/json/html)
        output_dir: 输出目录

    Returns:
        写入的文件路径

    Raises:
        ValueError: 不支持的格式
    """
    if fmt not in FORMAT_GENERATORS:
        raise ValueError(
            f"不支持的格式: {fmt}。支持: {', '.join(FORMAT_GENERATORS)}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = FORMAT_EXTENSIONS[fmt]
    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """
    CLI 入口。

    Args:
        argv: 命令行参数（默认 sys.argv[1:]）

    Returns:
        退出码 (0=成功, 1=失败)
    """
    parser = argparse.ArgumentParser(
        description="Sage 验证报告生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s                          # 生成 Markdown 报告\n"
            "  %(prog)s --format json             # 生成 JSON 报告\n"
            "  %(prog)s --format html             # 生成 HTML 报告\n"
            "  %(prog)s --rerun                   # 重新运行测试后生成报告\n"
            "  %(prog)s --input other.json        # 从指定文件加载结果\n"
        ),
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "html"],
        default="markdown",
        help="报告输出格式 (默认: markdown)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"输入 JSON 结果文件 (默认: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"报告输出目录 (默认: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="重新运行验证测试后生成报告（忽略 --input）",
    )

    args = parser.parse_args(argv)

    # 加载结果
    try:
        if args.rerun:
            print("重新运行验证测试...")
            data = rerun_and_load()
            print("测试运行完成，生成报告...")
        else:
            if not args.input.exists():
                print(
                    f"错误: 结果文件不存在: {args.input}\n"
                    f"请先运行: python scripts/verification/run_all.py",
                    file=sys.stderr,
                )
                return 1
            data = load_results(args.input)
    except json.JSONDecodeError as exc:
        print(f"错误: 结果文件格式无效: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"错误: 加载结果失败: {exc}", file=sys.stderr)
        return 1

    # 生成报告
    try:
        generator = FORMAT_GENERATORS[args.format]
        content = generator(data)
        output_path = write_report(content, args.format, args.output_dir)
        print(f"报告已生成: {output_path}")
        return 0
    except Exception as exc:
        print(f"错误: 生成报告失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
