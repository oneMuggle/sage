# backend/tools/codebase_search_tool.py
"""F2 (round5 批次 E): 工作区语义检索工具。

对工作区源码做 embedding 语义检索（增量索引 + 余弦 top-k）。与
grep_search（字面正则）/ symbol_search（Python AST 符号）互补——
语义检索命中"做这件事的代码在哪"这类概念查询。

前置条件：设置页已配置 embedding 模型（app_settings 的
modelSelections.embeddingModel）。未配置时返回引导性错误。
"""

from __future__ import annotations

from typing import Any

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.workspace_index import (
    _index_workspace,
    _search_workspace,
    load_embedding_config,
    workspace_index_stats,
)


class CodebaseSearchTool(BaseTool):
    """工作区语义检索（READ——只读工作区 + 写 sage 自有索引目录）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="codebase_search",
            description=(
                "在工作区源码中做语义检索：用自然语言描述要找的功能/逻辑，"
                "返回最相关的代码位置（文件 + 起始行 + 片段）。"
                "适合『处理 X 的代码在哪』『Y 逻辑的实现位置』类查询；"
                "精确字符串搜索请用 grep_search。首次调用会构建索引，可能较慢。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询，描述要找的代码功能",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数上限（默认 8，最大 20）",
                    },
                },
                "required": ["query"],
            },
        )

    def execute(  # noqa: PLR0911 — 配置/参数/绑定校验各自早退
        self, query: str = "", limit: int = 8, **kwargs: Any
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: query, limit）",
            )
        if not isinstance(query, str) or len(query.strip()) < 2:
            return ToolResult(success=False, error="query 至少需要 2 个字符")
        limit = max(1, min(20, int(limit)))

        config = load_embedding_config()
        if config is None:
            return ToolResult(
                success=False,
                error=(
                    "语义检索需要先在 设置 → 模型 中配置 embedding 模型"
                    "（用于向量化工作区源码）"
                ),
            )

        root = self._policy.workspace_root
        if not root:
            return ToolResult(
                success=False, error="codebase_search 需要绑定工作区（workspace）"
            )

        try:
            index_info = _index_workspace(root, config)
        except Exception as exc:  # noqa: BLE001 — 网络/解析失败降级为错误
            return ToolResult(success=False, error=f"索引构建失败: {exc}")

        try:
            results = _search_workspace(root, config, query.strip(), limit)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"检索失败: {exc}")

        return ToolResult(
            success=True,
            content={
                "query": query.strip(),
                "results": results,
                "index": {
                    "indexed_files_delta": index_info["indexed"],
                    "chunks_total": index_info["chunks"],
                    **workspace_index_stats(root),
                },
            },
        )
