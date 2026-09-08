"""学术文献检索技能 —— 通用「关键词检索 → 排序/筛选 → 整理摘要」流程模板。

设计目标(YAGNI):
- skill **不**内嵌 CNKI / PubMed / Google Scholar 的 HTML 解析。
  站点差异通过 ``academic_adapters`` 抽象为 URL 模板,
  结果解析交给 LLM 在 skill 描述/SKILL.md 里适配。
- 复用既有工具 ``web_fetch``(抓检索结果页)+ ``ask_user_question``(排序偏好)
  + ``memory_save``(记住这次检索),不引入新工具。
- 提供一个**示例工作流**,让用户能通过 ``skill_save`` 把流程沉淀下来,
  然后下次复用。

调用流程:
1. ``get_site_adapter(site).build_search_url(query, limit)`` → 检索 URL
2. ``web_fetch.execute(url=search_url)`` → 抓结果页 HTML/Markdown
3. (可选)``ask_user_question.execute(...)`` → 让用户挑排序方式
4. 把以上信息组装成结构化 prompt(给 LLM 看的),
   返回 ``SkillResult.content`` = 该 prompt,让 LLM 完成真正的语义提取
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillResult, SkillSchema
from .academic_adapters import get_site_adapter


class AcademicSearchSkill(BaseSkill):
    """学术文献检索技能。

    Args:
        site: 默认检索站点(默认 ``"cnki"``,需在 ``academic_adapters`` 注册)。
    """

    def __init__(self, site: str = "cnki") -> None:
        super().__init__()
        self._default_site = site

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="academic-search",
            description=(
                "通用学术文献检索流程模板:接收关键词 → 构造站点检索 URL → "
                "web_fetch 抓结果页 → ask_user_question 排序偏好 → "
                "整理结构化摘要供 LLM 解析。"
                "适用于 CNKI / PubMed / Google Scholar 等文献网站,"
                "具体页面解析由 LLM 适配,skill 只提供流程骨架。"
            ),
            triggers=[
                "找文献",
                "检索论文",
                "学术搜索",
                "literature search",
                "find papers",
                "academic search",
            ],
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词(必填)",
                    },
                    "site": {
                        "type": "string",
                        "description": (
                            "目标文献站点标识,如 cnki / pubmed / scholar。"
                            "需在 academic_adapters 注册。"
                        ),
                        "default": "cnki",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "每页条数(默认 10)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
            examples=[
                "帮我找 5 篇大语言模型综述",
                "检索近三年 Transformer 架构论文",
                "academic search: retrieval augmented generation 2024",
            ],
        )

    def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        """执行学术检索流程。

        Args:
            params: ``{"query": str, "site"?: str, "limit"?: int}``。
            context: 执行上下文,需要 ``tools`` dict 包含 ``web_fetch``、
                ``ask_user_question``(可选)。

        Returns:
            ``SkillResult(success=True, content=<结构化 prompt>)`` —— 该 prompt
            给 LLM 看,LLM 在此基础上完成实际页面解析 + 摘要生成。
            如果 web_fetch 工具缺失 → ``SkillResult(success=False, error=...)``。
        """
        query = params.get("query")
        if not isinstance(query, str) or not query.strip():
            return SkillResult(success=False, error="query 必须是非空字符串")

        site = params.get("site") or self._default_site
        limit = int(params.get("limit") or 10)

        # 1. 拿 adapter,构造检索 URL
        try:
            adapter = get_site_adapter(site)
            search_url = adapter.build_search_url(query, limit=limit)
        except ValueError as exc:
            return SkillResult(success=False, error=str(exc))

        # 2. 从 context 拿工具
        tools = context.get("tools", {}) or {}
        web_fetch = tools.get("web_fetch")
        if web_fetch is None:
            return SkillResult(success=False, error="web_fetch 工具不可用,无法抓检索结果页")

        # 3. 抓检索结果页
        fetch_result = web_fetch.execute(url=search_url)
        if not getattr(fetch_result, "success", False):
            err = getattr(fetch_result, "error", None) or "fetch failed"
            return SkillResult(success=False, error=f"web_fetch 抓取 {site} 检索页失败: {err}")

        fetch_content = getattr(fetch_result, "content", None) or ""

        # 4. 可选:问用户排序偏好
        ask_user = tools.get("ask_user_question")
        sort_pref = "relevance"
        user_options: Optional[List[str]] = None
        if ask_user is not None:
            user_options = ["按相关度", "按时间", "按引用数"]
            question_result = ask_user.execute(
                question=f"已从 {site} 检索到「{query}」的结果,如何排序?",
                options=user_options,
            )
            if getattr(question_result, "success", False):
                chosen = getattr(question_result, "content", None) or {}
                if isinstance(chosen, dict):
                    sort_pref = chosen.get("answer") or sort_pref
                elif isinstance(chosen, str):
                    sort_pref = chosen

        # 5. 组装结构化 prompt,让 LLM 完成真正的语义提取
        prompt = self._build_llm_prompt(
            query=query,
            site=site,
            limit=limit,
            search_url=search_url,
            sort_pref=sort_pref,
            fetch_content=fetch_content,
        )

        return SkillResult(
            success=True,
            content=prompt,
            metadata={
                "query": query,
                "site": site,
                "limit": limit,
                "sort_pref": sort_pref,
                "search_url": search_url,
                "asked_user": user_options is not None,
            },
        )

    @staticmethod
    def _build_llm_prompt(
        query: str,
        site: str,
        limit: int,
        search_url: str,
        sort_pref: str,
        fetch_content: str,
    ) -> str:
        """组装给 LLM 的结构化 prompt。"""
        snippet = (
            fetch_content
            if len(fetch_content) <= 4000
            else (fetch_content[:4000] + "\n... (已截断)")
        )
        return (
            f"用户需求:在 {site} 上检索「{query}」,期望 {limit} 条结果,"
            f"按「{sort_pref}」排序。\n\n"
            f"检索 URL:{search_url}\n\n"
            f"原始结果页内容(可能含 HTML,需要解析):\n"
            f"```\n{snippet}\n```\n\n"
            f"请解析结果页内容,提取 {limit} 条最相关的文献,每条给出:\n"
            f"1. 标题\n2. 作者\n3. 期刊/会议\n4. 年份\n5. 摘要(中文 2-3 句)\n\n"
            f"按「{sort_pref}」排序,Markdown 列表输出。"
        )


__all__ = ["AcademicSearchSkill"]
