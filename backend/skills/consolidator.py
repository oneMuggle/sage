"""ConsolidationService - 技能 LLM 巡检建议 (Round 5, 对标 hermes-agent curator)

定期（或手动触发）用 LLM 审阅 active 技能清单，发现**重复/过时**并产出
merge / archive / revise 建议。与 hermes 的差异点：Sage 的建议**只进审计
台账（append-only），不自动动文件**——人工审阅后走既有 archive /
draft-approve 流程收口，维持「可审计、可回滚」契约。

LLM provider 注入复用 ReviewService 的装配（同一 ``llm_provider.complete``
契约）；未配置时扫描端点返回 503，绝不自建 LLM 面。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 建议类型（archive 建议对 pinned 技能永不产出）
SUGGESTION_TYPES = ("merge", "archive", "revise")


class ConsolidationService:
    """LLM 驱动的技能巡检（产出建议，不直接修改技能）"""

    def __init__(self, llm_provider: Any, model: Optional[str] = None) -> None:
        self.llm_provider = llm_provider
        self._model = model

    @classmethod
    def from_review_service(cls, review_service: Any) -> Optional[ConsolidationService]:
        """从既有 ReviewService 复用 provider/model；未装配返回 None。"""
        if review_service is None:
            return None
        provider = getattr(review_service, "llm_provider", None)
        if provider is None:
            return None
        return cls(llm_provider=provider, model=getattr(review_service, "_model", None))

    async def scan(
        self,
        skills: List[Dict[str, Any]],
        pinned_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """扫描技能清单，返回归一化后的建议列表（不落库）。

        Args:
            skills: [{name, description, when_to_use, usage_count, stale}]
            pinned_names: pinned 技能 —— 永不出现在 archive 建议中

        Returns:
            [{type, skill_names, reason}]（LLM 失败/不可解析 → []）
        """
        pinned = set(pinned_names or [])
        if not skills:
            return []

        lines = [
            f"- {s.get('name', '')}: 描述={s.get('description', '')!r} "
            f"触发={s.get('when_to_use', '')!r} "
            f"使用次数={s.get('usage_count', 0)} {'[疑似过时]' if s.get('stale') else ''}"
            for s in skills
        ]
        prompt = (
            "以下是 AI 助手的技能清单（SKILL.md 技能库）。请做一次巡检：\n"
            "1. merge —— 功能/触发场景高度重叠的技能组（给出成员名单）；\n"
            "2. archive —— 长期零使用且内容过时的技能（给出名单）；\n"
            "3. revise —— 描述/触发条件写得含糊、值得修订的技能。\n\n"
            "严格要求：\n"
            "- 只基于清单内容判断，不要臆测；\n"
            "- 没有值得建议的就输出空数组；\n"
            "- 只输出 JSON 数组，元素形如 "
            '{"type": "merge", "skill_names": ["a", "b"], "reason": "…"}。\n\n'
            "技能清单:\n" + "\n".join(lines)
        )

        from backend.domain.message import Message

        try:
            turn = await self.llm_provider.complete(
                model=self._model,
                messages=[
                    Message(role="system", content="你是一个技能策展人。请输出 JSON 数组。"),
                    Message(role="user", content=prompt),
                ],
            )
        except Exception as exc:  # noqa: BLE001 — 巡检为增强能力, LLM 故障降级为无建议
            logger.warning("巡检 LLM 调用失败: %s", exc)
            return []
        if not getattr(turn, "text", None):
            logger.warning("巡检 LLM 返回空响应")
            return []
        return self._parse_suggestions(turn.text, pinned)

    @staticmethod
    def _parse_suggestions(
        raw: str, pinned: Optional[set] = None
    ) -> List[Dict[str, Any]]:
        """宽容解析 LLM 建议数组（容忍代码围栏/前后杂文），并做类型/名单过滤"""
        text = (raw or "").strip()
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        pinned = pinned or set()
        result: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            stype = item.get("type")
            names = item.get("skill_names")
            if stype not in SUGGESTION_TYPES or not isinstance(names, list):
                continue
            names = [n for n in names if isinstance(n, str) and n]
            if not names:
                continue
            if stype == "archive":
                names = [n for n in names if n not in pinned]
                if not names:
                    continue
            result.append(
                {
                    "type": stype,
                    "skill_names": names,
                    "reason": str(item.get("reason", "")),
                }
            )
        return result


# ------------------------------------------------------------------ #
# Global singleton（与 get_review_service 同模式）
# ------------------------------------------------------------------ #

_consolidation_service: Optional[ConsolidationService] = None


def get_consolidation_service() -> Optional[ConsolidationService]:
    """从 ReviewService 复用 provider 的惰性单例；未装配返回 None"""
    global _consolidation_service
    if _consolidation_service is None:
        try:
            from backend.skills.review_service import get_review_service

            _consolidation_service = ConsolidationService.from_review_service(
                get_review_service()
            )
        except Exception as exc:  # noqa: BLE001 — 巡检为增强能力
            logger.warning("ConsolidationService 初始化失败: %s", exc)
            return None
    return _consolidation_service


def reset_consolidation_service() -> None:
    """重置单例（测试用）"""
    global _consolidation_service
    _consolidation_service = None
