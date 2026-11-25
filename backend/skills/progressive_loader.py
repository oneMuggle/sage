"""ProgressiveSkillLoader - 三级渐进式技能加载（M3）

借鉴 LangChain Progressive Disclosure 模式：

  Level 1 (Metadata):   name + description + triggers  → 启动时加载
  Level 2 (Instructions): 完整 SKILL.md body           → 技能被选中时加载
  Level 3 (Resources):  scripts/, references/          → 执行时按需加载

结合 M2 评分分层：
  - Hot path: Level 1 全量 + 触发条件
  - Warm: Level 1 仅名称 + 描述
  - Cold: 仅索引，按需搜索加载

设计要点
--------

- **context budget**: 控制注入上下文的 token 预算（默认 2000 tokens ≈ 800 汉字）
- **lazy loading**: 完整 body 仅在技能被选中时加载
- **search**: 冷路径技能通过关键词匹配按需检索
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 上下文预算（tokens，1 token ≈ 0.4 汉字）
DEFAULT_CONTEXT_BUDGET_TOKENS = 2000


@dataclass
class SkillContext:
    """技能上下文（注入到 system prompt 的内容）。"""

    initial_context: str  # 启动时注入的技能摘要
    hot_skills: List[Dict[str, Any]] = field(default_factory=list)
    warm_skills: List[Dict[str, Any]] = field(default_factory=list)
    cold_count: int = 0
    estimated_tokens: int = 0


class ProgressiveSkillLoader:
    """三级渐进式技能加载。

    Example:
        >>> loader = ProgressiveSkillLoader(scoring_service=scoring)
        >>> ctx = await loader.build_context(skills, usage_map)
        >>> ctx.initial_context
        '- academic-search: 搜索学术论文 [触发: 搜索, 论文]\\n...'
    """

    def __init__(
        self,
        scoring_service: Any = None,
        context_budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
    ) -> None:
        self.scoring_service = scoring_service
        self.context_budget_tokens = context_budget_tokens

    async def build_context(
        self,
        skills: List[Dict[str, Any]],
        usage_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> SkillContext:
        """构建技能上下文（启动时调用）。

        根据评分分层，在 token 预算内生成技能摘要。

        Args:
            skills: [{name, description, when_to_use, triggers}, ...]
            usage_map: {name: {use_count, success_count, ...}}

        Returns:
            SkillContext: 包含 initial_context 和分层技能列表
        """
        if not skills:
            return SkillContext(initial_context="(无可用技能)")

        hot_skills: List[Dict[str, Any]] = []
        warm_skills: List[Dict[str, Any]] = []
        cold_skills: List[Dict[str, Any]] = []

        if self.scoring_service is not None:
            scores = self.scoring_service.compute_batch(skills, usage_map=usage_map or {})
            score_map = {s.name: s for s in scores}
            for skill in skills:
                name = skill.get("name", "")
                score = score_map.get(name)
                tier = score.tier if score else "cold"
                if tier == "hot":
                    hot_skills.append(skill)
                elif tier == "warm":
                    warm_skills.append(skill)
                else:
                    cold_skills.append(skill)
        else:
            warm_skills = list(skills)

        # 构建上下文（在预算内）
        budget = self.context_budget_tokens
        lines: List[str] = []
        estimated_tokens = 0

        # 优先 hot path
        for skill in hot_skills:
            line = self._format_skill_line(skill, include_triggers=True)
            line_tokens = self._estimate_tokens(line)
            if estimated_tokens + line_tokens > budget:
                break
            lines.append(line)
            estimated_tokens += line_tokens

        # 补充 warm
        for skill in warm_skills:
            line = self._format_skill_line(skill, include_triggers=False)
            line_tokens = self._estimate_tokens(line)
            if estimated_tokens + line_tokens > budget:
                break
            lines.append(line)
            estimated_tokens += line_tokens

        initial_context = "\n".join(lines) if lines else "(无技能在上下文预算内)"

        return SkillContext(
            initial_context=initial_context,
            hot_skills=hot_skills,
            warm_skills=warm_skills,
            cold_count=len(cold_skills),
            estimated_tokens=estimated_tokens,
        )

    def load_full_skill(self, skill_name: str, skill_body: str) -> str:
        """加载完整技能内容（技能被选中时调用）。

        Args:
            skill_name: 技能名称
            skill_body: SKILL.md 完整内容

        Returns:
            完整的技能指令（可直接注入 system prompt）
        """
        return f"\n\n===== 技能: {skill_name} =====\n{skill_body}\n"

    def search_cold_skills(
        self,
        query: str,
        cold_skills: List[Dict[str, Any]],
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """搜索冷路径技能（按需调用）。

        Args:
            query: 用户查询
            cold_skills: 冷路径技能列表
            top_k: 返回前 k 个结果

        Returns:
            匹配的技能列表（按相关性降序）
        """
        if not query or not cold_skills:
            return []

        query_lower = query.lower()
        scored: List[Tuple[float, Dict[str, Any]]] = []

        for skill in cold_skills:
            name = (skill.get("name") or "").lower()
            desc = (skill.get("description") or "").lower()
            when = (skill.get("when_to_use") or "").lower()
            text = f"{name} {desc} {when}"

            score = 0.0
            query_words = query_lower.split()
            for word in query_words:
                if word in text:
                    score += 1.0
                elif any(word[:3] in w for w in text.split() if len(w) >= 3):
                    score += 0.3

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:top_k]]

    def _format_skill_line(
        self,
        skill: Dict[str, Any],
        include_triggers: bool = False,
    ) -> str:
        """格式化单条技能摘要行。"""
        name = skill.get("name", "")
        desc = skill.get("description", "")
        if len(desc) > 60:
            desc = desc[:57] + "..."

        line = f"- {name}: {desc}"

        if include_triggers:
            triggers = skill.get("triggers", [])
            if triggers:
                trigger_str = ", ".join(triggers[:3])
                line += f" [触发: {trigger_str}]"

        return line

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """估算文本的 token 数（粗略：1 token ≈ 3 字符）。"""
        return max(1, len(text) // 3)


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_loader: Optional[ProgressiveSkillLoader] = None


def get_progressive_loader() -> ProgressiveSkillLoader:
    """获取全局 ProgressiveSkillLoader 单例。"""
    global _loader
    if _loader is None:
        try:
            from backend.skills.scoring import get_scoring_service
            scoring = get_scoring_service()
        except Exception:  # noqa: BLE001
            scoring = None
        _loader = ProgressiveSkillLoader(scoring_service=scoring)
    return _loader


def reset_progressive_loader() -> None:
    """重置单例（测试用）。"""
    global _loader
    _loader = None
