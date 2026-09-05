"""``observe_subagents`` 工具 —— 父 agent/conductor 读取子 agent 结构化快照。

只读工具：返回当前 run 内所有 task 的状态、当前步骤、进度预览。
不修改任何状态，不暴露 chain-of-thought / 完整 prompt / 凭据。

权限矩阵：仅对 conductor/父 agent 开放（由 tool-toggle 门控制）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.orchestration.snapshot_store import SnapshotStore
from backend.tools.base import BaseTool, ToolResult, ToolSchema

_TOOL_DESCRIPTION = (
    "观察当前 run 内所有子 agent 的运行状态快照。"
    "返回每个 task 的 status、当前 step、进度预览、错误信息。"
    "只读操作，不修改任何状态。"
)

_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {
            "type": "string",
            "description": "要查询的 run ID。留空则使用当前 run。",
        },
        "task_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "只返回指定 task 的快照。留空返回全部。",
        },
    },
    "required": [],
}


class ObserveSubagentsTool(BaseTool):
    """只读观察工具：返回子 agent 结构化运行快照。"""

    def __init__(
        self,
        snapshot_store: SnapshotStore,
        default_run_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._snapshot_store = snapshot_store
        self._default_run_id = default_run_id

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="observe_subagents",
            description=_TOOL_DESCRIPTION,
            parameters=_INPUT_SCHEMA,
        )

    async def execute_async(self, **kwargs: Any) -> ToolResult:
        run_id = kwargs.get("run_id") or self._default_run_id
        if not run_id:
            return ToolResult(success=False, error="run_id 缺失且无默认值")

        task_ids: Optional[List[str]] = kwargs.get("task_ids")

        snapshot = self._snapshot_store.get_run_snapshot(run_id)
        if snapshot is None:
            return ToolResult(success=False, error=f"run {run_id} 不存在")

        tasks_data = snapshot.to_dict()["tasks"]
        if task_ids:
            wanted = set(task_ids)
            tasks_data = [t for t in tasks_data if t["task_id"] in wanted]

        result = {
            "run_id": run_id,
            "run_status": snapshot.status,
            "last_event_seq": snapshot.last_event_seq,
            "tasks": tasks_data,
        }
        return ToolResult(success=True, content=json.dumps(result, ensure_ascii=False))

    def execute(self, **kwargs: Any) -> ToolResult:
        """同步调用也支持（纯内存读）。"""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            return ToolResult(
                success=False,
                error="observe_subagents 应在 async 上下文调用",
            )
        return asyncio.run(self.execute_async(**kwargs))


__all__ = ["ObserveSubagentsTool"]
