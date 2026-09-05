"""``orch_settings`` — 编排执行参数配置化（P2-9）。

从持久化 ``app_settings`` 读 ``orch`` 段（camelCase keys，与前端
``OrchSettings`` interface 对齐）。旧设置无 orch 段 → 全默认，绝不抛穿。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePath

from backend.data.settings_repo import SettingsRepository

#: app_settings.orch 段的 camelCase key → OrchSettings 字段名映射。
#: 与前端 src/entities/setting/types.ts 的 OrchSettings interface 对齐。
_RAW_KEYS = {
    "maxConcurrentSubagents": "max_concurrent_subagents",
    "maxAggregateChars": "max_aggregate_chars",
    "maxSubagentResultChars": "max_subagent_result_chars",
    "maxRetries": "max_retries",
    "maxLaneIterations": "max_lane_iterations",
    "maxSubagentIterations": "max_subagent_iterations",
    "scratchRoot": "scratch_root",
    "worktreeIsolation": "worktree_isolation",
}


@dataclass
class OrchSettings:
    max_concurrent_subagents: int = 4
    max_aggregate_chars: int = 120 * 1024
    max_subagent_result_chars: int = 50 * 1024
    max_retries: int = 2
    max_lane_iterations: int = 8
    #: 子代理（agent_tool）单次委派的 ReAct 迭代预算。默认 6 与原
    #: ``agent_tool.SUBAGENT_MAX_ITERATIONS`` 常量一致，仅开放可配。
    max_subagent_iterations: int = 6
    scratch_root: str = "orch_scratch"
    worktree_isolation: bool = False


def load_orch_settings() -> OrchSettings:
    """从持久化 app_settings 读 orch 段，缺省回落默认值。

    单键读取 + 类型守卫：orch 段是用户可控 JSON，单个坏键只回落该键默认，
    不因一个坏键把整段丢弃（防御 load_orch_settings 上游的脏数据）。
    """
    try:
        raw = SettingsRepository().get_json("app_settings") or {}
        orch = raw.get("orch", {}) if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 — 读配置失败回落默认，绝不抛穿
        orch = {}
    settings = OrchSettings()
    for camel, field_name in _RAW_KEYS.items():
        value = orch.get(camel)
        current = getattr(settings, field_name)
        if value is None:
            continue
        if isinstance(current, bool):
            if not isinstance(value, bool):
                continue
            settings = replace(settings, **{field_name: value})
        elif isinstance(current, int):
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            settings = replace(settings, **{field_name: value})
        elif isinstance(current, str) and isinstance(value, str):
            settings = replace(settings, **{field_name: _sanitize_scratch_root(value, current)})
    return settings


def _sanitize_scratch_root(value: str, fallback: str) -> str:
    """约束 scratch_root 为安全相对单目录名。

    拒绝绝对路径、含 ``..`` 的穿越、空字符串、以及带路径分隔符的多段
    输入。无效值回落为调用方传入的默认值，保证编排写入目录始终在
    预期数据目录内。
    """
    if not value:
        return fallback
    if PurePath(value).is_absolute():
        return fallback
    if ".." in value.split("/"):
        return fallback
    if "/" in value or "\\" in value:
        return fallback
    return value
