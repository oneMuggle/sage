# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Word 目录真页码刷新工具（Round 39）—— ``office_refresh_toc``。

把托管 .docx 内全部 TOC 域经 Word COM 更新为真页码并落盘（R29 的静态
缓存页码 → 打开即真页码）。与 office_repair_word 同一安全姿态：

- ``risk = WRITE_LOCAL``（刷新会写盘保存文档——INTERACTIVE 模式先审批）；
- ``requires_tool_context = True``（无活动 ToolExecutionContext 时
  registry 隐藏 schema，execute() 顶部 fail-closed）；
- file_path 经 ``_enforce_workspace`` 工作区围栏把守，workspace 取值
  复用 file_path 模式先例（绑定工作区优先，ad-hoc 回退父目录）。

Word COM / pywin32 不可用时返回带安装引导的失败（降级理由可直接展示），
不隐藏失败假装成功。

Public surface:

    OfficeRefreshTocTool(policy=None)   # name="office_refresh_toc"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import ToolExecutionContext


class OfficeRefreshTocTool(BaseTool):
    """刷新 docx 目录域为真页码（WRITE_LOCAL，Word COM 可选通道）。"""

    risk: RiskClass = RiskClass.WRITE_LOCAL
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_refresh_toc",
            description=(
                "把工作区内 .docx 的目录（TOC）域刷新为真页码并保存。适合"
                "office_create 生成带目录的报告后一步到位拿到可交付文档："
                "无需用户在 Word 里手动更新域。需本机安装 Microsoft Word + "
                "pywin32（pip install pywin32）；不可用时返回降级理由"
                "（此时可在 Word 中 Ctrl+A → F9 手动更新）。文档没有目录时"
                "成功返回 toc_count=0（no-op）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内待刷新目录 .docx 的路径",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(
        self,
        file_path: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        from backend.tools.context import current_tool_context

        ctx = current_tool_context()
        if self.requires_tool_context and ctx is None:
            return ToolResult(success=False, error="missing_tool_context")
        return self._refresh(ctx, file_path)

    def _refresh(self, ctx: Optional[ToolExecutionContext], file_path: Any) -> ToolResult:  # noqa: PLR0911
        """参数校验 + 路径围栏 + 刷新执行（拆出以控制 execute 分支数）。"""
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")

        # 与 office_repair_word 同一安全姿态：
        # _enforce_workspace（绑定工作区硬拒绝）+ 绝对路径 + 后缀白名单。
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        target = Path(file_path).expanduser()
        if not target.is_absolute():
            return ToolResult(
                success=False,
                error="file_path_absolute_required: 请传绝对路径",
            )
        if target.suffix.lower() != ".docx":
            return ToolResult(success=False, error="unsupported_file_type: 仅支持 .docx")
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        from backend.office.toc_refresh import refresh_toc_page_numbers

        workspace = _workspace_for_input(ctx, target)
        result = refresh_toc_page_numbers(target, workspace)
        if not result.ok:
            return ToolResult(success=False, error=f"toc_refresh_failed: {result.error}")
        return ToolResult(success=True, content=result.model_dump())


def _resolve_active_workspace(ctx: Optional[ToolExecutionContext]) -> Optional[Path]:
    """有活动绑定 → 绑定工作区 Path；否则 ``None``（DB 不可用同样吞掉）。"""
    if ctx is None or not ctx.session_id:
        return None
    try:
        from backend.data.database import get_database
        from backend.office.session_workspace import get_active_workspace

        conn = get_database().get_connection()
        binding = get_active_workspace(
            conn, ctx.session_id, expected_generation=ctx.binding_generation
        )
    except Exception:
        return None
    if binding is None:
        return None
    return Path(binding.workspace_path)


def _workspace_for_input(ctx: Optional[ToolExecutionContext], input_path: Path) -> Path:
    """file_path 模式的服务层 workspace：优先绑定工作区，回退输入父目录。"""
    binding_ws = _resolve_active_workspace(ctx)
    if binding_ws is not None:
        return binding_ws
    return input_path.parent
