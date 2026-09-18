#!/usr/bin/env python3
"""浏览器环境诊断 CLI（Phase D）。

用法:
    python scripts/check_browser_environment.py

输出 JSON 格式诊断结果到 stdout。
"""

from __future__ import annotations

import json
import sys

# 确保 backend 包可导入
sys.path.insert(0, ".")

from backend.tools.browser_diagnostics import run_all_checks


def main() -> None:
    result = run_all_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
