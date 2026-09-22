# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""DL2 后台下载任务查询/取消工具（Round 21）。

- ``download_status``：查单个任务或全部任务的当前状态（含完成后的
  path/bytes/sha256）；
- ``download_cancel``：取消 **pending**（排队未启动）的后台任务；running 的
  下载不可中断，如实返回不可取消。

任务表进程内存态（重启清零），经 ``download_jobs.get_download_job_manager()``
访问全局单例。风险级 WRITE_LOCAL（写工作区，与 web_fetch 家族一致不涉出网）。
"""

from __future__ import annotations

from typing import Any, Optional

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .download_jobs import get_download_job_manager


class DownloadStatusTool(BaseTool):
    """查询后台下载任务状态（单任务或全部）。"""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="download_status",
            description=(
                "查询后台下载任务状态。不带 job_id 返回全部任务；带 job_id 返回"
                "单个任务详情（含完成后的 path/bytes/sha256）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "后台下载任务 ID（submit 时返回）",
                    }
                },
                "required": [],
            },
        )

    def execute(
        self, job_id: Optional[str] = None, **kwargs: Any
    ) -> ToolResult:
        mgr = get_download_job_manager()
        if job_id and str(job_id).strip():
            job = mgr.status(str(job_id).strip())
            if job is None:
                return ToolResult(
                    success=False,
                    error=f"job_not_found: 任务 {job_id!r} 不存在或已被清理",
                )
            return ToolResult(success=True, content=job)
        jobs = mgr.all_jobs()
        if not jobs:
            return ToolResult(success=True, content={"jobs": [], "note": "无后台下载任务"})
        return ToolResult(success=True, content={"jobs": list(jobs.values())})


class DownloadCancelTool(BaseTool):
    """取消后台下载任务（仅 pending 可取消；running 不可中断）。"""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="download_cancel",
            description=(
                "取消后台下载任务。仅排队未启动（pending）的任务可取消；"
                "已开始下载的任务不可中断。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "后台下载任务 ID（submit 时返回）",
                    }
                },
                "required": ["job_id"],
            },
        )

    def execute(self, job_id: str = "", **kwargs: Any) -> ToolResult:
        mgr = get_download_job_manager()
        out = mgr.cancel(str(job_id or "").strip())
        if not out.get("ok"):
            return ToolResult(success=False, error=str(out.get("error", "cancel failed")))
        return ToolResult(success=True, content=out)
