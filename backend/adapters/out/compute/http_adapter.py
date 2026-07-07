"""HTTP 模式 ComputeAdapter — 本期预留空壳,未来实现。

设计意图
--------

为未来切换"subprocess CLI → HTTP 调用 ghm web 服务"留出端口,本期不实现。
当 subprocess 模式的冷启动延迟(~600ms+)成为瓶颈时,可改走本 adapter:

1. sage 启动时通过子进程拉起 ``ghm gui web --host 127.0.0.1 --port <auto>``,
   或要求用户预先启动 ghm web 服务
2. 复用现有 httpx 基础设施(参考 ``backend/adapters/out/llm/httpx_adapter.py``)
3. 每个 operation 配置 ``http_endpoint`` 字段(``backend/config/ghm.yaml`` 已预留)
4. 启动时调用 ``GET /api/health`` 确认连通

接入触发条件:见 ``docs/technical/19-ghm-integration.md §12``。

行为约定(本期)
---------------

- ``list_operations`` 与 ``SubprocessComputeAdapter`` 完全一致(共享 yaml
  ``operations`` 段),便于配置层透明切换 adapter。
- ``execute`` 抛 ``NotImplementedError``,消息指向本 plan 文档。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from sage_core import ComputeRequest, ComputeResult, ComputeSpec
from sage_core.repositories import ComputePort  # noqa: F401  (structural typing target)


@dataclass
class _OperationView:
    """yaml 中单个 operation 的轻量视图(仅用于 list_operations)。"""

    name: str
    description: str
    params_schema: Dict[str, Any] = field(default_factory=dict)


class HttpComputeAdapter:
    """``ComputePort`` 的 HTTP 实现(**预留空壳,本期不可用**)。

    Args:
        config:  ``backend/config/ghm.yaml`` 中 ``ghm`` 段。
    """

    _NOT_IMPLEMENTED_MSG = (
        "HttpComputeAdapter.execute 尚未实现。请使用 adapter=subprocess。"
        "本类作为未来升级路径预留接口"
        "(参见 docs/technical/19-ghm-integration.md §12)。"
    )

    def __init__(self, config: Dict[str, Any]) -> None:
        self._config = config
        self._operations: Dict[str, _OperationView] = {}
        for raw in config.get("operations", []):
            view = _OperationView(
                name=str(raw["name"]),
                description=str(raw.get("description", "")),
                params_schema=dict(raw.get("params_schema", {})),
            )
            self._operations[view.name] = view

    def list_operations(self) -> List[ComputeSpec]:
        """与 SubprocessComputeAdapter 行为一致(共享 operations 声明)。"""
        return [
            ComputeSpec(
                name=op.name,
                description=op.description,
                params_schema=dict(op.params_schema),
            )
            for op in self._operations.values()
        ]

    async def execute(self, req: ComputeRequest) -> ComputeResult:
        """**未实现** — 抛 ``NotImplementedError``。"""
        raise NotImplementedError(self._NOT_IMPLEMENTED_MSG)
