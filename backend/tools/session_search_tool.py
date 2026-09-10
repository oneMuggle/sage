"""Session Search Tool - 跨会话历史对话检索 (Round 2, 对标 hermes session search)

让 agent 能检索历史对话原文并自行综合回答（"上次我们怎么解决那个
构建报错"）—— 记忆库只存抽取后的条目，本工具补上原始对话的检索入口。
READ 级零副作用，无需审批。
"""

from __future__ import annotations

from typing import Any, Optional

from backend.tools.base import BaseTool, ToolResult, ToolSchema


class SessionSearchTool(BaseTool):
    """跨会话检索历史对话原文（FTS5 全文索引 + LIKE 回退）"""

    def __init__(self, index: Any = None, policy: Optional[Any] = None) -> None:
        super().__init__(policy=policy)
        self.index = index  # MessageSearchIndex；None 时 execute 惰性取全局单例

    def _get_index(self) -> Any:
        if self.index is not None:
            return self.index
        from backend.data.message_search import get_message_search_index

        return get_message_search_index()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="session_search",
            description=(
                "搜索历史对话原文（跨所有会话）。用于回忆之前讨论过的"
                "问题、方案、结论 —— 例如'上次我们怎么解决那个构建报错'。"
                "返回带会话归属的消息摘要，可配合 read 工具深入上下文。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词（支持中英文）",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "可选，限定在指定会话内搜索",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量 (默认 10, 上限 50)",
                    },
                },
                "required": ["query"],
            },
        )

    @staticmethod
    def _clamp_limit(limit: Any) -> int:
        """``[1, 50]`` clamp, 缺省 10"""
        try:
            n = int(limit) if limit is not None else 10
        except (TypeError, ValueError):
            return 10
        return max(1, min(n, 50))

    def execute(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: Any = 10,
        **kwargs: Any,
    ) -> ToolResult:
        """检索历史对话原文

        Args:
            query: 搜索关键词
            session_id: 可选会话过滤
            limit: 返回数量
        """
        if not query or not str(query).strip():
            return ToolResult(success=False, error="query 不能为空")
        try:
            index = self._get_index()
            results = index.search(
                str(query).strip(),
                session_id=session_id or None,
                limit=self._clamp_limit(limit),
            )
        except Exception as exc:  # noqa: BLE001 — 检索失败回传 LLM 可读错误
            return ToolResult(success=False, error=f"会话搜索失败: {exc}")

        if not results:
            return ToolResult(
                success=True,
                content={"query": query, "matches": [], "total": 0},
            )

        return ToolResult(
            success=True,
            content={"query": query, "matches": results, "total": len(results)},
        )
