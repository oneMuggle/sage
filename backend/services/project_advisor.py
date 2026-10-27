"""AI 项目进度顾问引擎（M3）。

收集项目多维度数据（里程碑状态、画像条目、逾期情况），调用 LLM
生成健康评分、风险提示和改进建议。结果缓存 30 分钟以避免频繁调用 LLM。

调用链:
  API route -> ProjectAdvisor.analyze() -> [cache | LLM] -> AdviceResult
  前端 -> ProjectAdvisorCard 展示 -> 用户手动刷新 -> POST .../ai/advice/refresh
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.services.llm_json import parse_json

logger = logging.getLogger(__name__)

# 30 分钟缓存 TTL（毫秒）
_CACHE_TTL_MS = 30 * 60 * 1000


@dataclass
class AdvisorRisk:
    """LLM 识别的单个风险项。"""

    description: str
    severity: str = "medium"  # low | medium | high
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "severity": self.severity,
            "suggestion": self.suggestion,
        }


@dataclass
class AdvisorSuggestion:
    """LLM 给出的单条改进建议。"""

    action: str
    reason: Optional[str] = None
    priority: str = "medium"  # low | medium | high

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "priority": self.priority,
        }


@dataclass
class AdviceResult:
    """项目顾问分析结果。"""

    health_score: int
    summary: str
    risks: List[AdvisorRisk] = field(default_factory=list)
    suggestions: List[AdvisorSuggestion] = field(default_factory=list)
    cached_at: Optional[int] = None
    raw_json: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "health_score": self.health_score,
            "summary": self.summary,
            "risks": [r.to_dict() for r in self.risks],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "cached_at": self.cached_at,
        }


class ProjectAdvisor:
    """项目进度顾问。

    收集项目多维度数据，调用 LLM 生成健康评分和建议。
    内置 30 分钟内存缓存。
    """

    def __init__(self, llm_client: Any = None) -> None:
        """初始化顾问。

        Args:
            llm_client: LLM 客户端（暴露 async complete(prompt) -> str）。
                为 None 时自动从 settings 构建。
        """
        if llm_client is not None:
            self._llm = llm_client
        else:
            from backend.orchestration.llm_factory import (  # noqa: ERA001
                build_llm_client_from_settings,
            )
            self._llm = build_llm_client_from_settings()

        # 内存缓存 — {project_id: (timestamp_ms, AdviceResult)}
        self._cache: Dict[str, tuple] = {}

    @property
    def available(self) -> bool:
        """LLM 客户端是否可用。"""
        return self._llm is not None

    async def analyze(
        self,
        project_id: str,
        force_refresh: bool = False,
    ) -> AdviceResult:
        """分析项目状态，返回健康评分和建议。

        Args:
            project_id: 项目 ID。
            force_refresh: 为 True 时忽略缓存，强制重新分析。

        Returns:
            AdviceResult 包含健康评分、摘要、风险和建议。

        Raises:
            ValueError: 项目不存在或数据不足。
            RuntimeError: LLM 调用失败。
        """
        # 检查缓存
        if not force_refresh:
            cached = self._get_cached(project_id)
            if cached is not None:
                return cached

        # 收集项目数据
        data = self._collect_data(project_id)

        # 构建 prompt 并调用 LLM
        prompt = self._build_prompt(data)
        raw_response = await self._llm.complete(prompt)
        result = self._parse_response(raw_response, project_id)

        # 写入缓存
        self._set_cached(project_id, result)

        return result

    def invalidate_cache(self, project_id: str) -> None:
        """清除指定项目的缓存。"""
        self._cache.pop(project_id, None)

    # ── 缓存管理 ─────────────────────────────────────────────────────────

    def _get_cached(self, project_id: str) -> Optional[AdviceResult]:
        """获取缓存结果（未过期时返回）。"""
        entry = self._cache.get(project_id)
        if entry is None:
            return None
        ts, result = entry
        now_ms = int(time.time() * 1000)
        if now_ms - ts > _CACHE_TTL_MS:
            self._cache.pop(project_id, None)
            return None
        # 返回带缓存时间戳的副本
        return AdviceResult(
            health_score=result.health_score,
            summary=result.summary,
            risks=result.risks,
            suggestions=result.suggestions,
            cached_at=ts,
            raw_json=result.raw_json,
        )

    def _set_cached(self, project_id: str, result: AdviceResult) -> None:
        """写入缓存。"""
        now_ms = int(time.time() * 1000)
        self._cache[project_id] = (now_ms, result)

    # ── 数据收集 ─────────────────────────────────────────────────────────

    def _collect_data(self, project_id: str) -> Dict[str, Any]:
        """收集项目多维度数据。"""
        from backend.data.project_milestone_repo import ProjectMilestoneRepository
        from backend.data.project_repo import ProjectRepository
        from backend.memory.project_profile import get_project_profile

        project = ProjectRepository().get(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")

        milestone_repo = ProjectMilestoneRepository()
        status_counts = milestone_repo.count_by_status(project_id)
        milestones = milestone_repo.list_by_project(project_id)

        # 检查逾期里程碑
        today = time.strftime("%Y-%m-%d")
        overdue = []
        for m in milestones:
            if (
                m.due_date
                and m.status not in ("completed",)
                and m.due_date < today
            ):
                overdue.append(
                    {
                        "title": m.title,
                        "due_date": m.due_date,
                        "status": m.status,
                        "days_overdue": _days_between(m.due_date, today),
                    }
                )

        # 获取画像条目数
        project_key = project.path or ""
        profile_count = 0
        if project_key:
            try:
                profile_entries = get_project_profile().list(project_key)
                profile_count = len(profile_entries)
            except Exception:
                logger.debug("Failed to load profile for %s", project_key, exc_info=True)

        return {
            "project": {
                "name": project.name,
                "type": project.project_type or "unknown",
                "stage": project.project_stage or "unknown",
                "description": (project.description or "")[:200],
            },
            "milestones": {
                "total": sum(status_counts.values()),
                "by_status": status_counts,
                "overdue": overdue,
            },
            "profile_entry_count": profile_count,
        }

    # ── Prompt 构建 ──────────────────────────────────────────────────────

    def _build_prompt(self, data: Dict[str, Any]) -> str:
        """构建 LLM prompt。"""
        project = data["project"]
        milestones = data["milestones"]
        by_status = milestones["by_status"]
        overdue = milestones["overdue"]

        overdue_text = ""
        if overdue:
            items = []
            for o in overdue[:5]:
                items.append(
                    f"  - \"{o['title']}\" 到期 {o['due_date']}，"
                    f"已逾期 {o['days_overdue']} 天（状态: {o['status']}）"
                )
            overdue_text = "\n".join(items)

        return f"""你是一位经验丰富的项目顾问。根据以下项目数据，给出简洁、可操作的建议。

## 项目信息
- 名称: {project['name']}
- 类型: {project['type']}
- 阶段: {project['stage']}
- 描述: {project['description'] or '未设置'}

## 里程碑状态
- 总计: {milestones['total']} 个
- 待开始: {by_status.get('pending', 0)}
- 进行中: {by_status.get('in_progress', 0)}
- 已完成: {by_status.get('completed', 0)}
- 已阻塞: {by_status.get('blocked', 0)}
- 画像条目数: {data['profile_entry_count']}

## 逾期里程碑
{overdue_text or '无逾期'}

## 评分标准（0-100）
- 90-100: 进展顺利，无风险，里程碑按时完成
- 70-89: 整体良好，有少量可管理风险
- 50-69: 存在问题需要关注（逾期/阻塞）
- 30-49: 多个问题，需要立即干预
- 0-29: 严重滞后，需要紧急重新规划

## 输出格式（严格 JSON）
{{
  "health_score": <0-100 整数>,
  "summary": "<1-2 句话总结项目状态>",
  "risks": [
    {{
      "description": "<风险描述>",
      "severity": "<low|medium|high>",
      "suggestion": "<应对建议>"
    }}
  ],
  "suggestions": [
    {{
      "action": "<具体行动>",
      "reason": "<原因>",
      "priority": "<low|medium|high>"
    }}
  ]
}}

注意：
- risks 最多 3 条，按 severity 降序
- suggestions 最多 3 条，按 priority 降序
- 只输出 JSON，不要额外说明"""

    # ── 响应解析 ─────────────────────────────────────────────────────────

    def _parse_response(self, raw: str, project_id: str) -> AdviceResult:
        """解析 LLM 响应为 AdviceResult。"""
        try:
            obj = parse_json(raw)
        except ValueError as exc:
            raise RuntimeError(
                f"LLM 响应中未找到 JSON (project={project_id}): {exc}"
            ) from exc

        health_score = int(obj.get("health_score", 50))
        health_score = max(0, min(100, health_score))
        summary = str(obj.get("summary", ""))

        risks = []
        for r in obj.get("risks", [])[:3]:
            risks.append(
                AdvisorRisk(
                    description=str(r.get("description", "")),
                    severity=str(r.get("severity", "medium")),
                    suggestion=r.get("suggestion"),
                )
            )

        suggestions = []
        for s in obj.get("suggestions", [])[:3]:
            suggestions.append(
                AdvisorSuggestion(
                    action=str(s.get("action", "")),
                    reason=s.get("reason"),
                    priority=str(s.get("priority", "medium")),
                )
            )

        return AdviceResult(
            health_score=health_score,
            summary=summary,
            risks=risks,
            suggestions=suggestions,
            raw_json=raw,
        )


def _days_between(date_a: str, date_b: str) -> int:
    """计算两个 YYYY-MM-DD 日期之间的天数差（b - a）。"""
    try:
        from datetime import datetime

        da = datetime.strptime(date_a, "%Y-%m-%d")  # noqa: DTZ007
        db = datetime.strptime(date_b, "%Y-%m-%d")  # noqa: DTZ007
        return (db - da).days
    except (ValueError, TypeError):
        return 0


__all__ = ["ProjectAdvisor", "AdviceResult", "AdvisorRisk", "AdvisorSuggestion"]
