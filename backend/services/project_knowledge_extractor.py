"""AI 对话知识提取引擎（M2）。

从会话对话历史中提取值得持久化的项目知识，写入 ProjectProfileStore。
提取的知识类别：convention / architecture / decision / goal / note。

调用链:
  API route -> ProjectKnowledgeExtractor.extract() -> LLM -> JSON
           -> 前端预览 -> 用户确认 -> confirm() -> ProjectProfileStore.add()
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProposedKnowledgeEntry:
    """LLM 建议的单个知识条目（待用户确认）。"""

    content: str
    category: str = "convention"
    importance: int = 5
    source_message_ids: List[str] = field(default_factory=list)
    reasoning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "category": self.category,
            "importance": self.importance,
            "source_message_ids": self.source_message_ids,
            "reasoning": self.reasoning,
        }


@dataclass
class ExtractionResult:
    """知识提取结果。"""

    entries: List[ProposedKnowledgeEntry]
    reasoning: str = ""
    tokens_used: int = 0
    raw_json: Optional[str] = None

    def to_preview(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self.entries]


class ProjectKnowledgeExtractor:
    """AI 对话知识提取引擎。

    使用方式::

        extractor = ProjectKnowledgeExtractor()
        result = await extractor.extract(
            project_id="uuid-xxx",
            session_id="session-yyy",
        )
        # result.entries -> [ProposedKnowledgeEntry, ...]
        # 用户确认后调用 confirm()
    """

    def __init__(self, llm_client: Any = None) -> None:
        if llm_client is not None:
            self._llm = llm_client
        else:
            from backend.orchestration.llm_factory import (
                build_llm_client_from_settings,
            )
            self._llm = build_llm_client_from_settings()

    @property
    def available(self) -> bool:
        return self._llm is not None

    async def extract(
        self,
        project_id: str,
        session_id: str,
        max_messages: int = 50,
    ) -> ExtractionResult:
        """从会话历史中提取知识条目建议。

        Args:
            project_id: 项目 ID
            session_id: 会话 ID
            max_messages: 最多分析的最近消息数

        Returns:
            ExtractionResult，包含建议条目列表。

        Raises:
            ValueError: 项目/会话不存在
            RuntimeError: LLM 不可用
        """
        if not self.available:
            raise RuntimeError(
                "LLM 客户端不可用，请在设置中配置 AI 端点"
            )

        project = self._load_project(project_id)
        project_key = getattr(project, "path", "") or ""
        messages = self._load_messages(session_id, limit=max_messages)

        if not messages:
            return ExtractionResult(
                entries=[], reasoning="会话中没有可分析的消息"
            )

        existing_entries = self._get_existing_profile_entries(project_key)

        prompt = self._build_prompt(
            project=project,
            messages=messages,
            existing_entries=existing_entries,
        )

        try:
            raw_response = await self._llm.complete(prompt)
        except Exception as exc:
            logger.error(
                "ProjectKnowledgeExtractor: LLM call failed: %s", exc
            )
            raise RuntimeError(f"LLM 调用失败: {exc}") from exc

        parsed = self._parse_response(raw_response)
        parsed.raw_json = raw_response
        return parsed

    def confirm(
        self,
        project_key: str,
        entries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """将用户确认的条目写入 ProjectProfileStore。

        Args:
            project_key: 项目 workspace 路径
            entries: 确认的条目列表，每项包含 content/category/importance

        Returns:
            {"created": int, "skipped": int, "ids": [str]}
        """
        from backend.memory.project_profile import get_project_profile

        store = get_project_profile()
        created = 0
        skipped = 0
        ids: List[str] = []

        for entry in entries:
            content = (entry.get("content") or "").strip()
            if not content:
                skipped += 1
                continue

            category = entry.get("category", "convention")
            importance = int(entry.get("importance", 5))

            result_id = store.add(
                project_key=project_key,
                content=content,
                category=category,
                importance=importance,
                source="ai_extraction",
            )
            if result_id:
                created += 1
                ids.append(result_id)
            else:
                skipped += 1

        # 写入后刷新快照，让下次 system prompt 注入新条目
        store.invalidate(project_key)

        return {"created": created, "skipped": skipped, "ids": ids}

    # -- 内部实现 -----------------------------------------------------------

    def _load_project(self, project_id: str) -> Any:
        from backend.data.project_repo import ProjectRepository

        repo = ProjectRepository()
        project = repo.get(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")
        return project

    def _load_messages(
        self, session_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """从会话加载消息（只取 user/assistant，按时间升序）。"""
        from backend.data.session_repo import MessageRepository

        msg_repo = MessageRepository()
        all_msgs = msg_repo.get_by_session(
            session_id, limit=10000, offset=0
        )

        # 过滤 user/assistant，取最近 N 条
        filtered = [
            m for m in all_msgs
            if m.role in ("user", "assistant")
        ]
        recent = filtered[-limit:] if len(filtered) > limit else filtered

        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content[:2000],  # 截断过长消息
            }
            for m in recent
        ]

    def _get_existing_profile_entries(
        self, project_key: str
    ) -> List[Dict[str, Any]]:
        """获取项目现有画像条目（用于去重提示）。"""
        if not project_key:
            return []
        from backend.memory.project_profile import get_project_profile

        store = get_project_profile()
        return store.list(project_key)

    def _build_prompt(
        self,
        project: Any,
        messages: List[Dict[str, Any]],
        existing_entries: List[Dict[str, Any]],
    ) -> str:
        """构建知识提取 prompt。"""
        project_type = getattr(project, "project_type", None) or "coding"
        project_desc = (
            getattr(project, "description", None) or "未描述"
        )

        sections: List[str] = []

        sections.append(
            "你是一个项目知识管理助手。从对话历史中提取值得持久化保存的"
            "项目知识。这些知识将在后续对话中作为上下文注入，帮助 AI "
            "更好地理解项目。\n\n"
            "你必须严格以 JSON 格式输出，不要包含任何非 JSON 内容。"
        )

        sections.append(
            f"## 项目信息\n"
            f"- 类型: {project_type}\n"
            f"- 描述: {project_desc}"
        )

        if existing_entries:
            existing_str = "\n".join(
                f"- [{e['category']}] {e['content']}"
                for e in existing_entries[:20]
            )
            sections.append(
                f"## 已有项目知识（避免重复提取）\n{existing_str}"
            )

        conversation_parts: List[str] = []
        for msg in messages:
            role_label = "用户" if msg["role"] == "user" else "助手"
            conversation_parts.append(
                f"[{role_label}] {msg['content'][:800]}"
            )
        conversation_str = "\n\n".join(conversation_parts)
        sections.append(f"## 对话历史\n{conversation_str}")

        sections.append(
            "## 提取规则\n"
            "从对话中提取以下类别的知识（如果存在的话）：\n"
            "- convention: 编码约定、命名规范、代码风格\n"
            "- architecture: 架构决策、设计模式、模块关系\n"
            "- decision: 技术选型、方案取舍（含原因）\n"
            "- goal: 项目目标、里程碑意图、需求意图\n"
            "- note: 其他值得记住的信息（环境配置、工作流偏好等）\n\n"
            "## 输出格式\n"
            "严格输出以下 JSON 结构（不要 markdown 代码块包裹）：\n"
            "{\n"
            '  "reasoning": "简要说明提取思路（1句话）",\n'
            '  "entries": [\n'
            "    {\n"
            '      "content": "知识内容（简洁，不超过 150 字）",\n'
            '      "category": "convention|architecture|decision|goal|note",\n'
            '      "importance": 重要性 1-10（10=最关键）,\n'
            '      "source_message_ids": ["msg_id1", "msg_id2"],\n'
            '      "reasoning": "为什么提取这条（1句话，可省略）"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "规则：\n"
            "1. 提取 0-10 条，只提取真正有价值的知识\n"
            "2. content 必须简洁（不超过150字），不要包含代码片段\n"
            "3. 不要与已有知识重复\n"
            "4. source_message_ids 填写对话中支持该知识点的消息 ID\n"
            "5. 如果对话中没有值得提取的知识，entries 为空数组"
        )

        return "\n\n".join(sections)

    def _parse_response(self, raw: str) -> ExtractionResult:
        """解析 LLM 的 JSON 响应。"""
        if not raw or not isinstance(raw, str):
            return ExtractionResult(
                entries=[], reasoning="LLM 返回空响应"
            )

        json_str = raw.strip()
        code_block_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?\s*```", json_str, re.DOTALL
        )
        if code_block_match:
            json_str = code_block_match.group(1).strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            start = json_str.find("{")
            end = json_str.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(json_str[start : end + 1])
                except json.JSONDecodeError:
                    logger.warning(
                        "ProjectKnowledgeExtractor: JSON parse failed"
                    )
                    return ExtractionResult(
                        entries=[],
                        reasoning="LLM 输出格式错误，无法解析",
                        raw_json=raw,
                    )
            else:
                return ExtractionResult(
                    entries=[],
                    reasoning="LLM 输出格式错误，无有效 JSON",
                    raw_json=raw,
                )

        reasoning = data.get("reasoning", "")
        raw_entries = data.get("entries", [])

        if not isinstance(raw_entries, list):
            return ExtractionResult(
                entries=[],
                reasoning="entries 不是列表",
                raw_json=raw,
            )

        entries = []
        for item in raw_entries:
            entry = self._parse_entry(item)
            if entry:
                entries.append(entry)

        return ExtractionResult(
            entries=entries,
            reasoning=reasoning,
            raw_json=raw,
        )

    def _parse_entry(
        self, data: dict
    ) -> Optional[ProposedKnowledgeEntry]:
        """解析单个知识条目 dict。"""
        if not isinstance(data, dict):
            return None
        content = data.get("content")
        if not content or not isinstance(content, str):
            return None

        category = data.get("category", "convention")
        valid_categories = (
            "convention", "architecture", "decision", "goal", "note"
        )
        if category not in valid_categories:
            category = "convention"

        importance = data.get("importance", 5)
        try:
            importance = max(1, min(int(importance), 10))
        except (ValueError, TypeError):
            importance = 5

        source_ids = data.get("source_message_ids", [])
        if not isinstance(source_ids, list):
            source_ids = []
        source_ids = [str(s) for s in source_ids if s]

        return ProposedKnowledgeEntry(
            content=content.strip()[:200],
            category=category,
            importance=importance,
            source_message_ids=source_ids,
            reasoning=data.get("reasoning"),
        )


__all__ = [
    "ProposedKnowledgeEntry",
    "ExtractionResult",
    "ProjectKnowledgeExtractor",
]
