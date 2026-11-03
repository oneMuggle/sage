"""前后端 LLM 重试默认值契约测试（防漂移）。

解析 ``src/entities/setting/types.ts`` 的 ``DEFAULT_SETTINGS``，断言四个重试键
与后端 ``RETRY_DEFAULTS`` 逐项相等。

背景: 2026-11-03 用户报告 win7 安装包中重试默认值不合理，且前后端各维护一套
默认值（后端 3/1.0/15.0/180，前端 3/1.0/30.0/180）。现统一由
``backend/core/retry_defaults.py`` 定义，本测试把两侧锁死，防止再次漂移。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.core.retry_defaults import RETRY_DEFAULTS, RETRY_KEYS, RETRY_RANGES

REPO_ROOT = Path(__file__).resolve().parents[3]
TYPES_TS = REPO_ROOT / "src" / "entities" / "setting" / "types.ts"

_DEFAULT_SETTINGS_START = "export const DEFAULT_SETTINGS"
_RETRY_LIMITS_START = "export const RETRY_LIMITS"


def _load_default_settings_block() -> str:
    source = TYPES_TS.read_text(encoding="utf-8")
    start = source.index(_DEFAULT_SETTINGS_START)
    end = source.index("\n};", start)
    return source[start:end]


def _load_retry_limits_block() -> str:
    source = TYPES_TS.read_text(encoding="utf-8")
    start = source.index(_RETRY_LIMITS_START)
    end = source.index("} as const", start)
    return source[start:end]


@pytest.mark.parametrize("key", RETRY_KEYS)
def test_frontend_default_matches_backend(key: str) -> None:
    block = _load_default_settings_block()
    match = re.search(rf"\b{key}\s*:\s*(-?\d+(?:\.\d+)?)\s*,", block)
    assert match is not None, f"types.ts DEFAULT_SETTINGS 中未找到 {key} 的数值字面量"

    frontend_value = float(match.group(1))
    backend_value = float(RETRY_DEFAULTS[key])
    assert frontend_value == backend_value, (
        f"{key} 前后端默认值漂移: 前端={frontend_value} 后端={backend_value}。"
        " 请同步 src/entities/setting/types.ts 与 backend/core/retry_defaults.py。"
    )


@pytest.mark.parametrize("key", RETRY_KEYS)
def test_default_value_within_declared_range(key: str) -> None:
    lower, upper = RETRY_RANGES[key]
    assert lower <= float(RETRY_DEFAULTS[key]) <= upper


@pytest.mark.parametrize("key", RETRY_KEYS)
def test_frontend_limits_match_backend_ranges(key: str) -> None:
    """前端 RETRY_LIMITS 与后端 RETRY_RANGES 必须完全一致（防漂移）。"""
    block = _load_retry_limits_block()
    lower_match = re.search(rf"\b{key}\s*:\s*\{{\s*min\s*:\s*(-?\d+(?:\.\d+)?)", block)
    upper_match = re.search(
        rf"\b{key}\s*:\s*\{{[^}}]*max\s*:\s*(-?\d+(?:\.\d+)?)", block
    )
    assert lower_match is not None, (
        f"types.ts RETRY_LIMITS 中未找到 {key} 的 min 数值字面量"
    )
    assert upper_match is not None, (
        f"types.ts RETRY_LIMITS 中未找到 {key} 的 max 数值字面量"
    )
    backend_lower, backend_upper = RETRY_RANGES[key]
    assert float(lower_match.group(1)) == float(backend_lower)
    assert float(upper_match.group(1)) == float(backend_upper)
