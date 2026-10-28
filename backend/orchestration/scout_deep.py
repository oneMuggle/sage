"""``scout_deep`` — 复杂任务深度调研 agent（2026-10-28）。

复用 WikiResearch 后端 ``deep_research()`` 管线，输出结构化 ``ResearchReport``。
供 ``plan_preflight.py`` 在 ``complexity == "complex"`` 时调用。

降级纪律：调研失败返回空报告（confidence=0），绝不阻塞编排流程。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.orchestration.llm_factory import load_llm_config_from_settings
from backend.orchestration.research_report import (
    ResearchReport,
    build_report_from_research_task,
)
from backend.wiki.deep_research import ResearchTask, deep_research
from backend.wiki.llm_context import make_llm_context
from backend.wiki.web_search import SearchProvider

logger = logging.getLogger(__name__)

# scout_deep 超时上限（秒）—— 与 SCOUT_TIMEOUT_ENV 一致，默认 120s
SCOUT_DEEP_TIMEOUT_S = 120


async def research(
    topic: str,
    project_path: Path,
    settings: Any = None,
) -> ResearchReport:
    """复杂任务深度调研。

    调用 WikiResearch 的 ``deep_research()`` 后端，输出结构化 ``ResearchReport``。

    Args:
        topic: 调研主题（通常来自用户 /plan 目标）
        project_path: 项目根目录路径
        settings: 编排设置（``OrchSettings``），用于读取搜索 API key 等配置

    Returns:
        ``ResearchReport``：结构化调研报告。失败时返回空报告（confidence=0）。

    降级纪律：
    - LLM 配置缺失 → 空报告
    - ``deep_research()`` 抛异常 → 空报告
    - ``task.status == "error"`` → 空报告
    - ``task.synthesis`` 为空 → 空报告
    """
    # 1. 构建 LLM 配置
    cfg = load_llm_config_from_settings()
    if cfg is None:
        logger.warning("scout_deep: LLM 配置缺失，降级返回空报告")
        return ResearchReport(topic=topic, confidence=0, estimated_effort="中")

    # 2. 构建 llm_call callable（复用 make_llm_context）
    try:
        ctx = make_llm_context(
            llm_base_url=cfg.get("base_url", ""),
            llm_api_key=cfg.get("api_key", ""),
            llm_model=cfg.get("model", ""),
        )
    except Exception as exc:
        logger.error("scout_deep: make_llm_context 失败: %s", exc)
        return ResearchReport(topic=topic, confidence=0, estimated_effort="中")

    # 3. 构建 ResearchTask
    task = ResearchTask(id=str(uuid4()), topic=topic)

    # 4. 从 settings 读取搜索配置（如有）
    search_api_key = ""
    search_provider = SearchProvider.TAVILY  # 默认 tavily
    if settings is not None:
        # 尝试从 settings 读取搜索 API key（字段名可能是 search_api_key 或 tavily_api_key）
        search_api_key = getattr(settings, "search_api_key", "") or getattr(
            settings, "tavily_api_key", ""
        )
        # 尝试从 settings 读取搜索 provider（字段名可能是 search_provider）
        provider_str = getattr(settings, "search_provider", "tavily")
        try:
            search_provider = SearchProvider(provider_str)
        except (ValueError, AttributeError):
            search_provider = SearchProvider.TAVILY

    # 5. 调用 deep_research()
    try:
        logger.info("scout_deep: 开始深度调研 topic=%s", topic)
        task = await deep_research(
            task=task,
            project_root=project_path,
            search_provider=search_provider,
            search_api_key=search_api_key,
            llm_call=ctx.llm_call,
            auto_ingest=False,  # scout_deep 不保存到 wiki（避免污染知识库）
        )
        logger.info("scout_deep: deep_research 完成 status=%s", task.status)
    except Exception as exc:
        logger.error("scout_deep: deep_research 抛异常: %s", exc)
        return ResearchReport(topic=topic, confidence=0, estimated_effort="中")

    # 6. 检查返回状态
    if task.status == "error" or not task.synthesis:
        logger.warning(
            "scout_deep: deep_research 失败或无综合结果 status=%s",
            task.status,
        )
        return ResearchReport(topic=topic, confidence=0, estimated_effort="中")

    # 7. 转换为 ResearchReport
    try:
        report = build_report_from_research_task(
            topic=task.topic,
            synthesis=task.synthesis,
            web_results=task.web_results,
            queries=task.queries,
        )
        logger.info(
            "scout_deep: 调研报告生成完成 findings=%d sources=%d confidence=%.2f",
            len(report.findings),
            len(report.sources),
            report.confidence,
        )
        return report
    except Exception as exc:
        logger.error("scout_deep: build_report_from_research_task 失败: %s", exc)
        return ResearchReport(topic=topic, confidence=0, estimated_effort="中")


__all__ = ["research", "SCOUT_DEEP_TIMEOUT_S"]
