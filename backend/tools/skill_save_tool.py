"""skill_save 工具 — LLM 显式触发技能沉淀的统一入口。

当用户明确表达"把这个流程存下来"或"沉淀成 skill"时,LLM 调本工具:
- 接收 LLM 传入的 ``tool_sequence``(刚执行的步骤)
- 委托 ``session_extractor.normalize_tool_sequence`` 校验/裁剪
- 委托 ``review_service.generate_draft(trigger_type="user_explicit_save", ...)`` 生成 SkillDraft
- 委托 ``SkillDraftStore.insert(draft)`` 持久化,供前端 /api/v1/skill-drafts 审批
- 返回 ``{draft_id, name, status: "pending"}`` 让 LLM 反馈给用户

风险声明:WRITE_LOCAL — 写本地 SQLite(已存在的 ``skill_drafts`` 表)。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.skills.draft_store import get_skill_draft_store
from backend.skills.review_service import get_review_service
from backend.skills.session_extractor import normalize_tool_sequence

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync code.

    Handles three cases:
    - No running event loop -- ``asyncio.run`` (creates + tears down).
    - Already inside an event loop -- run on a fresh thread with its own
      loop and wait synchronously.

    Pattern borrowed from ``backend.tools.wiki_tool``.
    """
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is None:
        return asyncio.run(coro)

    def _runner() -> Any:
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_runner)
        return future.result()


class SkillSaveTool(BaseTool):
    """显式触发技能沉淀的工具。

    LLM 在用户明确要求"把刚才的流程存为 skill"时调用本工具。
    """

    risk = RiskClass.WRITE_LOCAL

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="skill_save",
            description=(
                "把当前工具调用流程沉淀为可复用的技能草稿。"
                "当用户明确说'把这个流程存为 skill'或'下次也这么做'时调用。"
                "返回草稿 ID,等待用户审批。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "kebab-case 短名,3-40 字符,用于 SKILL.md 文件名。"
                            "例:'academic-search-cnki'"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "一句话描述 (≤ 80 字符)",
                    },
                    "when_to_use": {
                        "type": "string",
                        "description": (
                            "使用场景说明 (≥ 30 字符),必须具体到触发条件,"
                            "如 '当用户在 CNKI 检索学术文献时'"
                        ),
                    },
                    "tool_sequence": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "刚执行的工具调用序列 (最多 20 项),"
                            "每项形如 {tool: str, args: dict, result_summary?: str}。"
                            "skill_save 会自动过滤/裁剪脏数据。"
                        ),
                    },
                    "session_id": {
                        "type": "string",
                        "description": "可选;当前会话 ID,用于日志/溯源",
                    },
                },
                "required": [
                    "name",
                    "description",
                    "when_to_use",
                    "tool_sequence",
                ],
            },
        )

    def execute(  # noqa: PLR0911 — 校验→执行模式:4 类型校验 + 3 review 异常 + 1 store 异常 + 1 成功
        self,
        name: str,
        description: str,
        when_to_use: str,
        tool_sequence: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """沉淀流程为 skill 草稿。

        Args:
            name: 草稿名,kebab-case。
            description: 一句话描述。
            when_to_use: 触发条件。
            tool_sequence: 刚执行的工具调用列表。
            session_id: 可选会话 ID。

        Returns:
            ``ToolResult(success=True, content={draft_id, name, status})``
            或 ``ToolResult(success=False, error=...)``。
        """
        # 1. 基础类型校验
        if not isinstance(name, str) or not name.strip():
            return ToolResult(success=False, error="name 必须是非空字符串")
        if not isinstance(description, str) or not description.strip():
            return ToolResult(success=False, error="description 必须是非空字符串")
        if not isinstance(when_to_use, str) or not when_to_use.strip():
            return ToolResult(success=False, error="when_to_use 必须是非空字符串")
        if not isinstance(tool_sequence, list):
            return ToolResult(success=False, error="tool_sequence 必须是 list")

        # 2. 标准化工具序列
        normalized = normalize_tool_sequence(tool_sequence)

        # 3. 构造 review context
        context = {
            "session_id": session_id or "",
            "tool_calls": normalized,
            "user_provided_name": name,
            "user_provided_description": description,
            "user_provided_when_to_use": when_to_use,
        }

        # 4. 调 review pipeline 异步生成 SkillDraft
        try:
            service = get_review_service()
            draft = _run_async(
                service.generate_draft(
                    trigger_type="user_explicit_save", context=context
                )
            )
        except ValueError as exc:
            return ToolResult(
                success=False, error=f"review pipeline 拒绝草稿: {exc}"
            )
        except KeyError as exc:
            return ToolResult(
                success=False, error=f"review pipeline 缺字段: {exc}"
            )
        except Exception as exc:
            logger.exception("skill_save 工具执行失败")
            return ToolResult(
                success=False, error=f"review pipeline 异常: {exc}"
            )

        # 5. 持久化到 draft_store
        try:
            store = get_skill_draft_store()
            store.insert(draft)
        except Exception as exc:
            logger.exception("skill_save 持久化草稿失败")
            return ToolResult(
                success=False,
                error=f"草稿已生成但持久化失败: {exc}",
            )

        # 6. 返回结果
        return ToolResult(
            success=True,
            content={
                "draft_id": draft.id,
                "name": draft.name,
                "status": draft.status,
                "note": "草稿已生成,等待用户审批",
            },
            output=draft.id,
        )


__all__ = ["SkillSaveTool"]
