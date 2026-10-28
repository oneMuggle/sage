"""``test_scout_deep`` — ``scout_deep.py`` 单元测试（2026-10-28）。

覆盖 ``research()`` 函数的 7 条路径（5 条降级 + 1 条成功 + 1 条 settings 透传）：
1. LLM 配置缺失 → 空报告 (confidence=0)
2. ``make_llm_context`` 抛异常 → 空报告
3. ``deep_research`` 抛异常 → 空报告
4. ``deep_research`` 返回 status="error" → 空报告
5. ``deep_research`` 返回空 synthesis → 空报告
6. ``build_report_from_research_task`` 抛异常 → 空报告
7. 正常路径 → 结构化 ResearchReport

降级纪律：任何路径都不应抛异常，最差返回空报告（confidence=0）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.orchestration.research_report import ResearchReport
from backend.orchestration.scout_deep import research

PROJECT_PATH = Path("/tmp/test-project")


# ── 1. LLM 配置缺失 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_research_returns_empty_report_when_llm_config_missing() -> None:
    """LLM 配置缺失 → 降级返回空报告（confidence=0），不抛异常。"""
    with patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=None):
        report = await research(topic="认证系统", project_path=PROJECT_PATH)

    assert isinstance(report, ResearchReport)
    assert report.topic == "认证系统"
    assert report.confidence == 0
    assert report.findings == []
    assert report.sources == []


# ── 2. make_llm_context 失败 ──────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_research_returns_empty_report_when_make_llm_context_fails() -> None:
    """make_llm_context 抛异常 → 空报告。"""
    fake_cfg = {"base_url": "http://localhost:8080", "api_key": "key", "model": "gpt-4"}
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch(
        "backend.orchestration.scout_deep.make_llm_context",
        side_effect=RuntimeError("bad config"),
    )
    with p_cfg, p_ctx:
        report = await research(topic="认证系统", project_path=PROJECT_PATH)

    assert report.confidence == 0
    assert report.topic == "认证系统"


# ── 3. deep_research 抛异常 ───────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_research_returns_empty_report_when_deep_research_raises() -> None:
    """deep_research 抛异常（网络超时等）→ 空报告。"""
    fake_cfg = {"base_url": "", "api_key": "", "model": ""}
    fake_ctx = SimpleNamespace(llm_call=AsyncMock())
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch("backend.orchestration.scout_deep.make_llm_context", return_value=fake_ctx)
    p_deep = patch(
        "backend.orchestration.scout_deep.deep_research",
        side_effect=TimeoutError("LLM 超时"),
    )
    with p_cfg, p_ctx, p_deep:
        report = await research(topic="认证系统", project_path=PROJECT_PATH)

    assert report.confidence == 0
    assert report.findings == []


# ── 4. deep_research 返回 status="error" ──────────────────────────────────────


@pytest.mark.asyncio()
async def test_research_returns_empty_report_when_task_status_is_error() -> None:
    """deep_research 返回 task.status="error" → 空报告。"""
    fake_cfg = {"base_url": "", "api_key": "", "model": ""}
    fake_ctx = SimpleNamespace(llm_call=AsyncMock())
    error_task = SimpleNamespace(
        topic="认证系统",
        status="error",
        synthesis="",
        web_results=[],
        queries=[],
    )
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch("backend.orchestration.scout_deep.make_llm_context", return_value=fake_ctx)
    p_deep = patch("backend.orchestration.scout_deep.deep_research", return_value=error_task)
    with p_cfg, p_ctx, p_deep:
        report = await research(topic="认证系统", project_path=PROJECT_PATH)

    assert report.confidence == 0


# ── 5. deep_research 返回空 synthesis ─────────────────────────────────────────


@pytest.mark.asyncio()
async def test_research_returns_empty_report_when_synthesis_is_empty() -> None:
    """deep_research 完成但 synthesis 为空 → 空报告。"""
    fake_cfg = {"base_url": "", "api_key": "", "model": ""}
    fake_ctx = SimpleNamespace(llm_call=AsyncMock())
    empty_task = SimpleNamespace(
        topic="认证系统",
        status="done",
        synthesis="",
        web_results=[],
        queries=[],
    )
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch("backend.orchestration.scout_deep.make_llm_context", return_value=fake_ctx)
    p_deep = patch("backend.orchestration.scout_deep.deep_research", return_value=empty_task)
    with p_cfg, p_ctx, p_deep:
        report = await research(topic="认证系统", project_path=PROJECT_PATH)

    assert report.confidence == 0


# ── 6. build_report_from_research_task 抛异常 ─────────────────────────────────


@pytest.mark.asyncio()
async def test_research_returns_empty_report_when_build_report_fails() -> None:
    """build_report_from_research_task 抛异常 → 空报告。"""
    fake_cfg = {"base_url": "", "api_key": "", "model": ""}
    fake_ctx = SimpleNamespace(llm_call=AsyncMock())
    good_task = SimpleNamespace(
        topic="认证系统",
        status="done",
        synthesis="## 关键发现\nOAuth 2.0 是标准方案。",
        web_results=[],
        queries=["oauth 2.0 best practices"],
    )
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch("backend.orchestration.scout_deep.make_llm_context", return_value=fake_ctx)
    p_deep = patch("backend.orchestration.scout_deep.deep_research", return_value=good_task)
    p_build = patch(
        "backend.orchestration.scout_deep.build_report_from_research_task",
        side_effect=ValueError("解析失败"),
    )
    with p_cfg, p_ctx, p_deep, p_build:
        report = await research(topic="认证系统", project_path=PROJECT_PATH)

    assert report.confidence == 0
    assert report.topic == "认证系统"


# ── 7. 正常路径 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_research_happy_path_returns_structured_report() -> None:
    """正常路径：deep_research 返回有效结果 → 结构化 ResearchReport。"""
    fake_cfg = {"base_url": "", "api_key": "", "model": ""}
    fake_ctx = SimpleNamespace(llm_call=AsyncMock())
    good_task = SimpleNamespace(
        topic="认证系统",
        status="done",
        synthesis="## 核心架构\n事件驱动设计。\n\n## 关键发现\nOAuth 2.0 是标准方案。",
        web_results=[
            SimpleNamespace(url="https://oauth.net/2", title="OAuth 2.0", snippet="标准协议"),
            SimpleNamespace(url="https://example.com/auth", title="Auth Guide", snippet="指南"),
        ],
        queries=["oauth 2.0", "认证系统设计"],
    )
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch("backend.orchestration.scout_deep.make_llm_context", return_value=fake_ctx)
    p_deep = patch("backend.orchestration.scout_deep.deep_research", return_value=good_task)
    with p_cfg, p_ctx, p_deep:
        report = await research(topic="认证系统", project_path=PROJECT_PATH)

    assert report.confidence > 0
    assert report.topic == "认证系统"
    assert len(report.findings) > 0
    assert len(report.sources) == 2
    assert report.synthesis  # 非空


# ── 8. Settings 透传（搜索配置） ──────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_research_passes_search_config_from_settings() -> None:
    """Settings 中的搜索配置应透传给 deep_research。"""
    fake_cfg = {"base_url": "", "api_key": "", "model": ""}
    fake_ctx = SimpleNamespace(llm_call=AsyncMock())
    good_task = SimpleNamespace(
        topic="T",
        status="done",
        synthesis="## 结果\n内容",
        web_results=[],
        queries=[],
    )
    settings = SimpleNamespace(
        search_api_key="sk-test-key",
        search_provider="tavily",
    )
    mock_deep_research = AsyncMock(return_value=good_task)
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch("backend.orchestration.scout_deep.make_llm_context", return_value=fake_ctx)
    p_deep = patch("backend.orchestration.scout_deep.deep_research", mock_deep_research)
    with p_cfg, p_ctx, p_deep:
        report = await research(topic="T", project_path=PROJECT_PATH, settings=settings)

    assert report.confidence > 0
    # 验证 deep_research 被调用时传入了正确的 search_api_key
    call_kwargs = mock_deep_research.call_args
    assert call_kwargs.kwargs.get("search_api_key") == "sk-test-key" or (
        call_kwargs.args and "sk-test-key" in str(call_kwargs)
    )


# ── 9. Settings 为 None 时不崩溃 ──────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_research_works_with_settings_none() -> None:
    """settings=None 时使用默认搜索配置，不崩溃。"""
    fake_cfg = {"base_url": "", "api_key": "", "model": ""}
    fake_ctx = SimpleNamespace(llm_call=AsyncMock())
    good_task = SimpleNamespace(
        topic="T",
        status="done",
        synthesis="## 结果\n内容",
        web_results=[],
        queries=[],
    )
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch("backend.orchestration.scout_deep.make_llm_context", return_value=fake_ctx)
    p_deep = patch("backend.orchestration.scout_deep.deep_research", return_value=good_task)
    with p_cfg, p_ctx, p_deep:
        report = await research(topic="T", project_path=PROJECT_PATH, settings=None)

    assert report.confidence > 0


# ── 10. deep_research 返回 None synthesis 字段 ────────────────────────────────


@pytest.mark.asyncio()
async def test_research_handles_none_synthesis_gracefully() -> None:
    """task.synthesis 是 None（而非空字符串）→ 也视为空报告。"""
    fake_cfg = {"base_url": "", "api_key": "", "model": ""}
    fake_ctx = SimpleNamespace(llm_call=AsyncMock())
    none_task = SimpleNamespace(
        topic="T",
        status="done",
        synthesis=None,
        web_results=[],
        queries=[],
    )
    p_cfg = patch("backend.orchestration.scout_deep.load_llm_config_from_settings", return_value=fake_cfg)
    p_ctx = patch("backend.orchestration.scout_deep.make_llm_context", return_value=fake_ctx)
    p_deep = patch("backend.orchestration.scout_deep.deep_research", return_value=none_task)
    with p_cfg, p_ctx, p_deep:
        report = await research(topic="T", project_path=PROJECT_PATH)

    assert report.confidence == 0
