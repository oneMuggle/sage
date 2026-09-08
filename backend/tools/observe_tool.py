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

    def _read_snapshot(
        self,
        run_id: str,
        task_ids: Optional[List[str]],
    ) -> tuple:
        """O4 (2026-09-08): 同步读取 run 快照 —— 纯内存读，无需事件循环。

        Returns:
            ``(payload, None)`` 成功；``(None, error_message)`` 失败。
        """
        snapshot = self._snapshot_store.get_run_snapshot(run_id)
        if snapshot is None:
            return None, f"run {run_id} 不存在"

        tasks_data = snapshot.to_dict()["tasks"]
        if task_ids:
            wanted = set(task_ids)
            tasks_data = [t for t in tasks_data if t["task_id"] in wanted]

        return (
            {
                "run_id": run_id,
                "run_status": snapshot.status,
                "last_event_seq": snapshot.last_event_seq,
                "tasks": tasks_data,
            },
            None,
        )

    async def execute_async(self, **kwargs: Any) -> ToolResult:
        run_id = kwargs.get("run_id") or self._default_run_id
        if not run_id:
            return ToolResult(success=False, error="run_id 缺失且无默认值")

        payload, error = self._read_snapshot(run_id, kwargs.get("task_ids"))
        if error is not None:
            return ToolResult(success=False, error=error)
        return ToolResult(
            success=True, content=json.dumps(payload, ensure_ascii=False)
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """同步读 —— 与 execute_async 等价（快照读是纯内存操作）。

        O4 (2026-09-08): 此前本方法在检测到运行中的事件循环时自拒
        （"应在 async 上下文调用"）—— 恰好命中 run_loop 对非特判工具的
        同步直调路径（observe_subagents 不在 agent.py 的 execute_async
        special-case 清单），工具注册后 conductor 永远拿到错误。快照读
        无异步依赖，直接同步返回。
        """
        run_id = kwargs.get("run_id") or self._default_run_id
        if not run_id:
            return ToolResult(success=False, error="run_id 缺失且无默认值")

        payload, error = self._read_snapshot(run_id, kwargs.get("task_ids"))
        if error is not None:
            return ToolResult(success=False, error=error)
        return ToolResult(
            success=True, content=json.dumps(payload, ensure_ascii=False)
        )


__all__ = ["ObserveSubagentsTool"]
