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


    async def draft_from_suggestion(  # noqa: PLR0911 — 守卫链逐条 return
        self,
        suggestion: Dict[str, Any],
        skill_docs: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        """把 merge/revise 建议生成为技能草稿 JSON（Round 9）。

        archive 建议 / LLM 输出不可解析 / 校验失败 → None。
        """
        stype = suggestion.get("type")
        if stype not in ("merge", "revise"):
            return None
        names = [n for n in suggestion.get("skill_names", []) if n in skill_docs]
        if not names:
            return None

        if stype == "merge":
            instruction = (
                "以下是若干个功能重叠的技能（SKILL.md 全文）。请把它们合并为"
                "**一个**新技能：保留各技能的可复用步骤，合并触发场景。\n"
                '只输出 JSON：{"name": "新技能名(小写连字符)", '
                '"description": "不超过80字", "when_to_use": "至少30字的触发场景", '
                '"content": "完整 SKILL.md(含 frontmatter, 内容含 '
                '## 步骤/## 触发条件/## 示例)"}\n\n'
            )
        else:
            instruction = (
                "以下技能的描述/触发条件写得含糊，值得修订。请产出修订后的"
                "**同名**技能：仅改进 description/when_to_use 的清晰度与"
                "正文的可执行性，不改技能用途。\n"
                '只输出 JSON：{"name": "同名", '
                '"description": "不超过80字", "when_to_use": "至少30字", '
                '"content": "修订后完整 SKILL.md"}\n\n'
            )

        docs_text = "".join(
            f"\n\n==== 技能: {n} ====\n{skill_docs[n]}" for n in names
        )
        prompt = instruction + docs_text

        from backend.domain.message import Message
        from backend.skills.review_service import ReviewService

        try:
            turn = await self.llm_provider.complete(
                model=self._model,
                messages=[
                    Message(role="system", content="你是一个技能策展人。请输出 JSON。"),
                    Message(role="user", content=prompt),
                ],
            )
        except Exception as exc:  # noqa: BLE001 — 单条草稿失败跳过
            logger.warning("草稿生成 LLM 调用失败: %s", exc)
            return None
        text = (getattr(turn, "text", None) or "").strip()
        if not text:
            return None

        brace_start, brace_end = text.find("{"), text.rfind("}")
        if brace_start == -1 or brace_end <= brace_start:
            logger.warning("巡检草稿输出无 JSON 对象")
            return None
        try:
            parsed = json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            logger.warning("巡检草稿输出不可解析为 JSON")
            return None
        if not isinstance(parsed, dict):
            return None

        try:
            ReviewService._validate_skill_name(parsed.get("name", ""))
            ReviewService._validate_skill_schema(parsed)
        except (ValueError, KeyError) as exc:
            logger.warning("巡检草稿校验失败 (%s): %s", stype, exc)
            return None
        return {
            "name": parsed["name"],
            "description": parsed["description"],
            "when_to_use": parsed["when_to_use"],
            "content": parsed["content"],
        }

    async def generate_drafts(
        self,
        suggestions: List[Dict[str, Any]],
        skill_docs: Dict[str, str],
        draft_store: Any,
        source: str = "consolidation_scan",
    ) -> int:
        """逐条生成草稿并入库（pending，走既有审批面）。返回入库数。"""
        import time as _time
        import uuid as _uuid

        from backend.skills.review_service import SkillDraft

        created = 0
        for suggestion in suggestions:
            draft_fields = await self.draft_from_suggestion(suggestion, skill_docs)
            if draft_fields is None:
                continue
            try:
                draft_store.insert(
                    SkillDraft(
                        id=str(_uuid.uuid4()),
                        name=draft_fields["name"],
                        description=draft_fields["description"],
                        when_to_use=draft_fields["when_to_use"],
                        content=draft_fields["content"],
                        trigger_type="consolidation",
                        source_session_id="",
                        source_context={
                            "consolidation": True,
                            "suggestion": suggestion,
                            "source": source,
                        },
                        status="pending",
                        created_at=int(_time.time() * 1000),
                    )
                )
                created += 1
            except Exception as exc:  # noqa: BLE001 — 单条失败跳过
                logger.warning("巡检草稿入库失败: %s", exc)
        return created


def collect_skill_docs(names: List[str]) -> Dict[str, str]:
    """读取指定技能的 SKILL.md 全文（草稿合并/修订输入）。缺失跳过。"""
    try:
        from backend.skills.loader import get_skill_loader

        loader = get_skill_loader()
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill loader 获取失败: %s", exc)
        return {}
    docs: Dict[str, str] = {}
    for name in names:
        try:
            content = loader.read(name)
        except Exception:  # noqa: BLE001 — 单个读取失败跳过
            content = None
        if content:
            docs[name] = content
    return docs


def collect_active_skills() -> List[Dict[str, Any]]:
    """收集 active（未归档）技能的巡检输入清单。

    经 InprocSkillAdapter（与 legacy_routes 同一技能面）惰性获取；
    适配器不可用（如测试环境无技能注册）返回 []。
    """
    try:
        from backend.api.legacy_routes import _get_skill_adapter

        adapter = _get_skill_adapter()
    except Exception as exc:  # noqa: BLE001 — 巡检为增强能力
        logger.warning("技能清单获取失败: %s", exc)
        return []
    skills: List[Dict[str, Any]] = []
    for ext in adapter.list_skills_extended():
        if ext.get("archived"):
            continue
        name = ext.get("name", "")
        skills.append(
            {
                "name": name,
                "description": ext.get("description", ""),
                "when_to_use": ext.get("when_to_use", ""),
                "usage_count": adapter.usage_count(name),
            }
        )
    return skills


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
