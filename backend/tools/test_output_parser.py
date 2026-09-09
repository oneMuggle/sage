# backend/tools/test_output_parser.py
"""D-3 (round5 批次 C→D): 测试输出失败用例结构化解析。

bash 跑测试非零退出时,LLM 只能在 30KiB 截断文本里自己找失败清单——
本模块把 pytest / vitest / jest 的失败行解析成结构化数据,由 bash 工具
附加到 ToolResult.content["test_failures"],让模型直接拿到确定性清单。

设计口径:
- 纯函数、零依赖、只扫输入的**末尾 200 行**(测试摘要总在尾部);
- 无命中返回 None(调用方不附加字段,零开销路径);
- 只做行级解析,不构造 AST/正则灾难回溯。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: 只扫描尾部行数——测试框架的摘要/失败清单恒在输出尾部
_TAIL_LINES = 200

_PYTEST_FAILED_RE = re.compile(r"^FAILED (.+?)(?: - .*)?$")
_PYTEST_SUMMARY_RE = re.compile(r"=+ (?:short test summary info|=+ )?([\d]+ failed)")
_PYTEST_PASSED_RE = re.compile(r"(\d+) passed")

_VITEST_FAIL_FILE_RE = re.compile(r"^ FAIL\s+(\S+)")
_JEST_FAIL_FILE_RE = re.compile(r"^FAIL (\S+)")
_VITEST_FAIL_TEST_RE = re.compile(r"^\s*[×✗]\s+(.+?)(?:\s+\(\d+\.?\d*\s*(?:ms|s)\))?$")
_JS_SUMMARY_RE = re.compile(r"Tests:?\s+(\d+) failed(?:[,\s|]+(\d+)\s+passed)?")


def _tail(text: str, max_lines: int = _TAIL_LINES) -> List[str]:
    lines = text.splitlines()
    return lines[-max_lines:]


def _parse_pytest(lines: List[str]) -> Optional[Dict[str, Any]]:
    failures: List[str] = []
    summary_failed: Optional[int] = None
    summary_passed: Optional[int] = None
    for line in lines:
        match = _PYTEST_FAILED_RE.match(line)
        if match:
            failures.append(match.group(1).strip())
            continue
        if _PYTEST_SUMMARY_RE.search(line):
            m = re.search(r"(\d+) failed", line)
            if m:
                summary_failed = int(m.group(1))
            m = _PYTEST_PASSED_RE.search(line)
            if m:
                summary_passed = int(m.group(1))
    if not failures and not summary_failed:
        return None
    result: Dict[str, Any] = {"framework": "pytest", "failures": failures}
    if summary_failed is not None:
        result["failed"] = summary_failed
    if summary_passed is not None:
        result["passed"] = summary_passed
    if failures and summary_failed is not None:
        # -q 模式 FAILED 行与 --tb 输出共存:以行清单为准
        result["failed"] = max(summary_failed, len(failures))
    return result


def _parse_js_family(lines: List[str]) -> Optional[Dict[str, Any]]:
    fail_files: List[str] = []
    fail_tests: List[str] = []
    summary_failed: Optional[int] = None
    summary_passed: Optional[int] = None
    for line in lines:
        m = _VITEST_FAIL_FILE_RE.match(line) or _JEST_FAIL_FILE_RE.match(line)
        if m:
            fail_files.append(m.group(1))
            continue
        m = _VITEST_FAIL_TEST_RE.match(line)
        if m:
            fail_tests.append(m.group(1).strip())
            continue
        m = _JS_SUMMARY_RE.search(line)
        if m:
            summary_failed = int(m.group(1))
            if m.group(2):
                summary_passed = int(m.group(2))
    if summary_failed is None and not fail_files and not fail_tests:
        return None
    result: Dict[str, Any] = {
        "framework": "vitest",
        "failures": fail_tests or fail_files,
    }
    if summary_failed is not None:
        result["failed"] = summary_failed
    if summary_passed is not None:
        result["passed"] = summary_passed
    return result


def parse_test_failures(stdout: str, stderr: str) -> Optional[Dict[str, Any]]:
    """从测试命令输出中解析失败用例清单。

    支持 pytest 与 vitest/jest 的常规输出形态（含 ``-ra`` / ``-v`` 摘要）。
    stdout 与 stderr 合并扫描（pytest 摘要走 stdout、构建器报错走 stderr）。

    Returns:
        ``{"framework", "failures": [...], "failed"?, "passed"?}``，
        无测试失败特征时返回 None。
    """
    combined = list(_tail(stdout)) + list(_tail(stderr))
    return _parse_pytest(combined) or _parse_js_family(combined)
