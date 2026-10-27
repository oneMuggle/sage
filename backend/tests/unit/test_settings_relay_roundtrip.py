"""settings relay 往返（snake_case ↔ camelCase）回归测试。

模拟 Electron relay 的真实链路：

    前端 camelCase payload
      → electron/invoke.ts ``camelToSnakeKeys``（递归转 snake）
      → 后端 ``to_camel``（只认 ALIASES 显式登记的对）
      → ``validate_settings_shape``（白名单校验）

缺 ALIASES 条目时，键翻不回 camel，白名单报 400，而前端
``saveSettings`` 的 ``catch {}`` 会静默吞掉 —— 用户看到"改了没生效"。
2026-10-27 事故即由此产生（maxIterations / logTimezone / useFolderPicker）。
"""

from __future__ import annotations

import re

from backend.data.settings_canonicalizer import to_camel, validate_settings_shape


def _snake(key: str) -> str:
    """复刻 electron/invoke.ts 的 camelToSnakeKeys 单键转换。"""
    return re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), key)


def _relay(value):
    """复刻 electron relay 的递归 camel→snake 转换。"""
    if isinstance(value, dict):
        return {_snake(k): _relay(v) for k, v in value.items()}
    return value


def test_orch_payload_survives_relay_snake_roundtrip() -> None:
    """编排 / 通用 / Wiki 段经 relay 往返后仍能翻回 camel 并通过白名单。

    2026-10-27 回归：``maxIterations`` 缺 snake 别名，编排 Tab 每次保存
    必 400（前端整体 spread 提交 orch 段，必带 maxIterations）。同时
    ``logTimezone`` / ``useFolderPicker`` 同属该类回归，一并修复。
    """
    camel_payload = {
        "orch": {
            "maxConcurrentSubagents": 4,
            "maxToolCallsPerRun": 100,
            "maxScoutIterations": 4,
            "maxPlannerIterations": 8,
            "maxIterations": 0,
        },
        "logTimezone": "UTC",
        "wiki": {"useFolderPicker": True},
    }
    translated = to_camel(_relay(camel_payload))

    # 三处回归键必须翻回 camel
    assert translated["orch"]["maxIterations"] == 0
    assert "max_iterations" not in translated["orch"]
    assert translated["logTimezone"] == "UTC"
    assert "log_timezone" not in translated
    assert translated["wiki"]["useFolderPicker"] is True
    assert "use_folder_picker" not in translated["wiki"]
    # 整份 payload 必须过白名单（不抛 = 通过）
    validate_settings_shape(translated)


def test_flat_multiword_keys_survive_relay_roundtrip() -> None:
    """顶层多词 camel 键（如 llmRetryMaxAttempts）也不能在 relay 后丢键。"""
    camel_payload = {
        "autoMemory": True,
        "llmRetryMaxAttempts": 3,
        "llmRetryBaseDelayS": 1.0,
        "llmRetryMaxDelayS": 15.0,
        "llmTotalTimeoutS": 0,
    }
    translated = to_camel(_relay(camel_payload))

    for key in camel_payload:
        assert key in translated, f"relay 往返后丢键: {key}"
    validate_settings_shape(translated)
