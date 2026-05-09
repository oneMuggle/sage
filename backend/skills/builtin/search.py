"""
搜索技能 - 网络搜索并整理结果
"""
from typing import Dict, Any, List

from ..base import BaseSkill, SkillSchema, SkillResult


class SearchSkill(BaseSkill):
    """搜索技能 - 网络搜索并整理结果"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="search",
            description="搜索网络信息并整理结果",
            triggers=["搜索", "查一下", "帮我找", "search", "lookup"],
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "结果数量",
                        "default": 5
                    }
                },
                "required": ["query"]
            },
            examples=[
                "帮我搜索一下 Python 异步编程",
                "查一下 ChatGPT 最新消息"
            ]
        )

    def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        """执行搜索"""
        query = params.get("query")
        limit = params.get("limit", 5)

        # 获取 web_search 工具
        tools = context.get("tools", {})
        web_search = tools.get("web_search")
        
        if web_search is None:
            return SkillResult(
                success=False,
                error="搜索工具不可用"
            )

        # 执行搜索
        result = web_search.execute(query=query, limit=limit)

        # 格式化结果
        if result.success and result.content:
            formatted = self._format_results(result.content.get("results", []))
            return SkillResult(
                content=formatted,
                metadata={
                    "query": query,
                    "count": len(result.content.get("results", []))
                }
            )

        return SkillResult(
            success=False,
            error=result.error or "搜索失败"
        )

    def _format_results(self, results: List[Dict]) -> str:
        """格式化搜索结果"""
        if not results:
            return "没有找到相关结果。"

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get('title', '无标题')
            snippet = r.get('snippet', '')
            url = r.get('url', '')
            
            lines.append(f"{i}. **{title}**")
            lines.append(f"   {snippet}")
            if url:
                lines.append(f"   🔗 {url}")
            lines.append("")

        return "\n".join(lines)
