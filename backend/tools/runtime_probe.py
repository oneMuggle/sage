"""``runtime_probe`` 工具 — 发现本机可用的运行时。

按设计只做只读探测，不触发执行审批。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.runtime import (
    ProbeRequest,
    ProbeResult,
    RuntimeInfo,
)

# 自注册: 保证工具类被直接实例化时 (如 doctor check / 单测) 也能拿到已注册
# 的适配器。register_default_adapters 幂等, 与 register_all_tools 的重复调用无副作用。
from backend.tools.adapters import register_default_adapters
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.runtime_adapter import AdapterContext, registry
from backend.tools.runtime_safe_run import safe_run

register_default_adapters()

logger = logging.getLogger(__name__)


class RuntimeProbeTool(BaseTool):
    """发现 Python / Node.js 等运行时，结果结构化输出。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="runtime_probe",
            description=(
                "探测本机可用的编程语言运行时（Python、Node.js 等），"
                "返回每个运行时的路径、版本和兼容性。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要探测的语言列表；空数组表示全部已注册适配器",
                    },
                    "include_tools": {
                        "type": "boolean",
                        "description": "是否同时探测工具（npm、pnpm、yarn、bun 等）",
                        "default": True,
                    },
                    "target_version": {
                        "type": "string",
                        "description": '可选的最低版本约束（如 ">=3.10")，用于兼容性标记',
                    },
                    "include_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "额外手动追加的搜索路径",
                    },
                },
            },
        )

    def execute(  # type: ignore[override]
        self,
        *,
        languages: Optional[List[str]] = None,
        include_tools: bool = True,
        target_version: Optional[str] = None,
        include_paths: Optional[List[str]] = None,
        workspace_root: Optional[str] = None,
        **_kwargs: Any,
    ) -> ToolResult:
        request = ProbeRequest(
            languages=tuple(languages or ()),
            include_tools=include_tools,
            target_version=target_version,
            include_paths=tuple(include_paths or ()),
        )
        root = Path(workspace_root) if workspace_root else Path.cwd()
        ctx = AdapterContext(workspace_root=root, safe_run=safe_run)

        adapter_languages = (
            list(request.languages) if request.languages else registry.languages()
        )

        runtimes: List[RuntimeInfo] = []
        errors: List[str] = []
        for lang in adapter_languages:
            adapter = registry.get(lang)
            if adapter is None:
                errors.append(f"未注册的运行时语言: {lang}")
                continue
            try:
                found = adapter.discover(request, ctx)
            except Exception as exc:  # noqa: BLE001
                logger.warning("runtime_probe %s 失败: %s", lang, exc)
                errors.append(f"{lang}: {exc}")
                continue
            runtimes.extend(found)

        recommended = next((r.path for r in runtimes if r.is_default), None)
        if not recommended and runtimes:
            for r in runtimes:
                if r.capabilities.can_execute and r.is_compatible is not False:
                    recommended = r.path
                    break
            if not recommended:
                recommended = runtimes[0].path

        result = ProbeResult(
            runtimes=runtimes,
            recommended=recommended,
            errors=tuple(errors),
        )
        return ToolResult(
            success=True,
            content=result.to_dict(),
        )


__all__ = ["RuntimeProbeTool"]
