"""M2 显式限制 — 工具执行统一策略。

claw-code ``concept.md`` §4 原则 2「显式限制」：byte/turn/glob caps + 超时，
失败可预测。

本模块提供：
- ``ToolPolicy``：不可变 dataclass，承载 timeout + 各上限。
- ``ToolPolicy.from_config(dict)``：从已加载配置 dict 构造（缺字段回退默认）。

**领域纯净性**：本模块不读文件、不读时钟。配置加载由调用方（应用层）
负责把 yaml → dict 后传入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 默认值与方案 §3.2 设计一致
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_OUTPUT_BYTES = 256_000
_DEFAULT_MAX_RESULT_ITEMS = 200
_DEFAULT_MAX_READ_BYTES = 2_000_000
_DEFAULT_MAX_TOOL_CALLS_PER_RUN = 25


@dataclass(frozen=True)
class ToolPolicy:
    """工具执行的统一上限。

    Fields:
        timeout_seconds:    中心超时（覆盖分散硬编码）
        max_output_bytes:   单次工具输出 byte 上限（分发处统一截断）
        max_result_items:   list/search 类条数上限
        max_read_bytes:     read_file 字节上限（先于行切片）
        max_tool_calls_per_run: 单次 run 内工具调用总数守卫
    """

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES
    max_result_items: int = _DEFAULT_MAX_RESULT_ITEMS
    max_read_bytes: int = _DEFAULT_MAX_READ_BYTES
    max_tool_calls_per_run: int = _DEFAULT_MAX_TOOL_CALLS_PER_RUN

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> ToolPolicy:
        """从已加载的配置 dict 构造，缺字段回退默认值。

        调用方负责把 yaml/JSON 解析成 dict；本方法只读 dict 字段。
        """
        defaults = cls()
        return cls(
            timeout_seconds=cfg.get("timeout_seconds", defaults.timeout_seconds),
            max_output_bytes=cfg.get("max_output_bytes", defaults.max_output_bytes),
            max_result_items=cfg.get("max_result_items", defaults.max_result_items),
            max_read_bytes=cfg.get("max_read_bytes", defaults.max_read_bytes),
            max_tool_calls_per_run=cfg.get(
                "max_tool_calls_per_run", defaults.max_tool_calls_per_run
            ),
        )
