"""Deep Research 流程。

实现多步骤研究：网络搜索 → 收集来源 → LLM 综合 → 自动 Ingest。
"""
from typing import List

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .ingest import IngestConfig, ingest_source
from .web_search import SearchProvider, WebSearchResult, multi_query_search

logger = logging.getLogger(__name__)


@dataclass
class ResearchTask:
    """研究任务。"""

    id: str
    topic: str
    status: str = "queued"  # queued, searching, synthesizing, done, error
    queries: List[str] = field(default_factory=list)
    web_results: List[WebSearchResult] = field(default_factory=list)
    synthesis: str = ""
    saved_path: str = ""
    error: str = ""


async def generate_search_queries(topic: str, llm_call: Callable) -> List[str]:
    """使用 LLM 生成多个搜索查询。

    Args:
        topic: 研究主题
        llm_call: LLM 调用函数

    Returns:
        list[str]: 生成的搜索查询列表
    """
    prompt = f"""你是一个研究助手。针对以下研究主题，生成 3-5 个不同的搜索查询，以获取全面的信息。

研究主题: {topic}

要求:
1. 每个查询应该从不同角度探索主题
2. 查询应该具体且有针对性
3. 使用英文或中文（根据主题语言）
4. 输出 JSON 数组格式

输出格式:
["query 1", "query 2", "query 3"]

只输出 JSON 数组，不要其他内容。"""

    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm_call(messages, temperature=0.7)

        # 解析 JSON
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:-3].strip()
        elif response.startswith("```"):
            response = response[3:-3].strip()

        queries = json.loads(response)

        if not isinstance(queries, list):
            raise ValueError("LLM 返回的不是数组")

        return [str(q) for q in queries[:5]]  # 最多 5 个查询

    except Exception as e:
        logger.error(f"生成搜索查询失败: {e}")
        # 回退：使用主题作为查询
        return [topic]


async def synthesize_research(
    topic: str,
    web_results: List[WebSearchResult],
    llm_call: Callable,
) -> str:
    """使用 LLM 综合搜索结果。

    Args:
        topic: 研究主题
        web_results: 网络搜索结果
        llm_call: LLM 调用函数

    Returns:
        str: 综合报告（Markdown 格式）
    """
    # 构建来源摘要
    sources_text = []
    for i, result in enumerate(web_results[:10], 1):  # 最多 10 个来源
        sources_text.append(
            f"[{i}] {result.title}\n    URL: {result.url}\n    摘要: {result.snippet}"
        )

    sources_str = "\n\n".join(sources_text)

    prompt = f"""你是一个研究助手。基于以下网络搜索结果，为研究主题撰写一份综合报告。

研究主题: {topic}

网络搜索结果:
{sources_str}

要求:
1. 撰写一份结构化的 Markdown 报告
2. 包含以下部分:
   - 概述（2-3 段）
   - 关键发现（使用列表）
   - 详细分析（分小节）
   - 结论
3. 在适当位置引用来源（使用 [1], [2] 等标记）
4. 在报告末尾列出所有引用的来源
5. 使用中文撰写（除非主题是其他语言）
6. 确保内容准确，不要编造信息

输出格式: Markdown"""

    messages = [{"role": "user", "content": prompt}]

    try:
        return await llm_call(messages, temperature=0.3)

    except Exception as e:
        logger.error(f"综合研究失败: {e}")
        return f"# 研究综合失败\n\n主题: {topic}\n\n错误: {str(e)}"


async def deep_research(
    task: ResearchTask,
    project_root: Path,
    search_provider: SearchProvider,
    search_api_key: str = "",
    search_base_url: str = "",
    llm_call: Callable = None,
    ingest_config: IngestConfig = None,
    auto_ingest: bool = True,
) -> ResearchTask:
    """执行 Deep Research 流程。

    Args:
        task: 研究任务
        project_root: 项目根目录
        search_provider: 搜索提供者
        search_api_key: 搜索 API 密钥
        search_base_url: 搜索基础 URL
        llm_call: LLM 调用函数
        ingest_config: Ingest 配置（用于自动 Ingest）
        auto_ingest: 是否自动 Ingest 综合报告

    Returns:
        ResearchTask: 更新后的研究任务
    """
    if llm_call is None:
        task.status = "error"
        task.error = "LLM 调用函数未提供"
        return task

    try:
        # Step 1: 生成搜索查询
        task.status = "searching"
        logger.info(f"开始研究: {task.topic}")

        task.queries = await generate_search_queries(task.topic, llm_call)
        logger.info(f"生成了 {len(task.queries)} 个搜索查询")

        # Step 2: 执行网络搜索
        task.web_results = await multi_query_search(
            queries=task.queries,
            provider=search_provider,
            api_key=search_api_key,
            base_url=search_base_url,
            max_results_per_query=5,
        )
        logger.info(f"收集到 {len(task.web_results)} 个搜索结果")

        if not task.web_results:
            task.status = "error"
            task.error = "未找到相关搜索结果"
            return task

        # Step 3: LLM 综合
        task.status = "synthesizing"
        task.synthesis = await synthesize_research(task.topic, task.web_results, llm_call)
        logger.info("研究综合完成")

        # Step 4: 自动 Ingest（可选）
        if auto_ingest and ingest_config is not None:
            task.status = "ingesting"

            # 将综合报告保存为临时文件
            temp_file = project_root / ".llm-wiki" / f"research_{task.id}.md"
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file.write_text(task.synthesis, encoding="utf-8")

            try:
                # 执行 Ingest
                result = await ingest_source(
                    config=ingest_config,
                    project_root=project_root,
                    source_file_path=temp_file,
                    llm_call=llm_call,
                    http_post=None,  # Ingest 会使用配置中的嵌入 API
                )

                task.saved_path = result.wiki_page_path
                logger.info(f"研究结果已保存到: {result.wiki_page_path}")

            except Exception as e:
                logger.error(f"自动 Ingest 失败: {e}")
                # Ingest 失败不影响整体流程

            # 清理临时文件
            if temp_file.exists():
                temp_file.unlink()

        task.status = "done"
        logger.info(f"研究完成: {task.topic}")

    except Exception as e:
        logger.error(f"Deep Research 失败: {e}")
        task.status = "error"
        task.error = str(e)

    return task
