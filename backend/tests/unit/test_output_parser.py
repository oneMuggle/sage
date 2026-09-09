# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""D-3 (round5 批次 D): 测试输出失败解析纯函数测试。"""

import pytest

from backend.tools.test_output_parser import parse_test_failures

pytestmark = pytest.mark.unit


def test_pytest_failed_lines_and_summary():
    stdout = (
        "============================= test session starts =============================\n"
        "collected 10 items\n"
        "\n"
        "tests/test_a.py F....F.\n"
        "=================================== FAILURES ===================================\n"
        "=================================== short summary info =========================\n"
        "FAILED tests/test_a.py::test_login_renders - assert 1 == 2\n"
        "FAILED tests/test_b.py::test_logout - RuntimeError: boom\n"
        "========================= 2 failed, 8 passed in 0.5s =========================\n"
    )
    result = parse_test_failures(stdout, "")
    assert result is not None
    assert result["framework"] == "pytest"
    assert result["failed"] == 2
    assert result["passed"] == 8
    assert result["failures"] == [
        "tests/test_a.py::test_login_renders",
        "tests/test_b.py::test_logout",
    ]


def test_vitest_fail_file_and_tests():
    stdout = (
        " FAIL  src/__tests__/app.test.tsx\n"
        "   × renders header (12 ms)\n"
        "   × renders footer (3 ms)\n"
        "\n"
        " Test Files  1 failed | 3 passed (4)\n"
        "      Tests  2 failed | 30 passed (32)\n"
    )
    result = parse_test_failures(stdout, "")
    assert result is not None
    assert result["framework"] == "vitest"
    assert result["failed"] == 2
    assert result["passed"] == 30
    assert "renders header" in result["failures"][0]


def test_stderr_scanned_too():
    stderr = "FAILED tests/test_x.py::test_one - ValueError\n"
    result = parse_test_failures("", stderr)
    assert result is not None
    assert result["failures"] == ["tests/test_x.py::test_one"]


def test_no_test_features_returns_none():
    result = parse_test_failures("hello world\n", "some random error\n")
    assert result is None


def test_tail_only_scan_keeps_cost_bounded():
    # 大量无关行在前,pytest 摘要在尾部 → 仍能命中
    noise = "\n".join(f"noise line {i}" for i in range(5000))
    stdout = noise + "\nFAILED tests/test_tail.py::test_tail_case\n"
    result = parse_test_failures(stdout, "")
    assert result is not None
    assert result["failures"] == ["tests/test_tail.py::test_tail_case"]


def test_jest_style_fail_block():
    stdout = (
        "FAIL src/app.test.ts\n"
        "  ● app › does the thing\n"
        "\n"
        "Tests:       1 failed, 4 passed, 5 total\n"
    )
    result = parse_test_failures(stdout, "")
    assert result is not None
    assert result["framework"] == "vitest"
    assert result["failed"] == 1
