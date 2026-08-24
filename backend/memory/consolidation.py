"""
Memory Consolidation Pipeline - 记忆压缩管道
负责工作记忆到情景记忆的自动摘要和压缩
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from backend.memory.summary import FAILED, READY, SessionSummaryStore, _redact_error_message

if TYPE_CHECKING:
    from backend.core.legacy.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ConsolidationPipeline:
    """
    记忆压缩管道

    功能:
    1. 压缩工作记忆（生成摘要）
    2. 将摘要存入情景记忆
    3. 可选：使用 LLM 辅助摘要生成
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        summary_store: Optional[SessionSummaryStore] = None,
    ):
        self.llm_client = llm_client
        self.summary_store = summary_store

    def compress_working_memory(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """
        压缩工作记忆为摘要

        Args:
            messages: 工作记忆中的消息列表（调用方负责按 session 取消息）

        Returns:
            生成的摘要内容；批次三 step 4 起：LLM 失败/空响应**绝不**回退
            到 fallback 文本,而是返回 ``None``,由 :meth:`consolidate`
            写 ``status=FAILED`` 行（spec §4.3 step 4 "不伪装为普通事实"）。
            只有未配置 LLM 时才使用 fallback,这是产品明确定义的"无 LLM
            模式",与失败语义分开。
        """
        if not messages:
            return None

        messages_text = "\n".join(
            [f"[{msg.get('role', 'unknown')}]: {msg.get('content', '')[:300]}" for msg in messages]
        )

        if self.llm_client:
            try:
                prompt = f"""请将以下对话压缩为一段简洁的摘要（100字以内），保留关键信息和决策:

{messages_text}

摘要:"""
                result = self.llm_client.complete(prompt)
                if result and result.strip():
                    return result.strip()
                # LLM 已配置但返回空 → 不回退,直接当失败
                logger.warning(
                    "LLM 摘要生成返回空内容 (session=%s),走 FAILED 分支",
                    getattr(self, "_current_session_id", "<unknown>"),
                )
                return None
            except Exception as e:
                logger.warning(
                    "LLM 摘要生成异常 (session=%s): %s",
                    getattr(self, "_current_session_id", "<unknown>"),
                    e,
                )
                return None

        # 未配置 LLM:产品允许的降级路径,使用 fallback
        return self._fallback_summary(messages)

    def _fallback_summary(self, messages: List[Dict[str, Any]]) -> str:
        """简单的回退摘要策略"""
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if user_msgs:
            first = user_msgs[0].get("content", "")[:80]
            user_msgs[-1].get("content", "")[:80]
            return f"对话围绕「{first}...」等话题展开，共 {len(messages)} 条消息"
        return f"共 {len(messages)} 条消息的对话"

    def save_compressed(
        self,
        episodic_memory,
        summary: str,
        session_id: Optional[str] = None,
        importance: int = 5,
        message_count: int = 0,
    ) -> str:
        """
        将压缩后的摘要存入情景记忆

        Args:
            episodic_memory: EpisodicMemory 实例
            summary: 摘要内容
            session_id: 关联的会话 ID
            importance: 重要性评分
            message_count: 被压缩的消息数量

        Returns:
            生成的记忆 ID
        """
        return episodic_memory.save(
            content=f"对话摘要: {summary}",
            importance=importance,
            metadata={
                "source": "consolidation_pipeline",
                "message_count": message_count,
            },
            session_id=session_id,
            memory_type="summary",
        )

    def consolidate(
        self, memory_manager, session_id: Optional[str] = None, importance_threshold: int = 5
    ) -> Optional[str]:
        """
        完整的记忆压缩流程（只处理指定会话的工作记忆）

        Args:
            memory_manager: MemoryManager 实例
            session_id: 关联的会话 ID，透传给 WorkingMemory 的取/清操作；
                None 表示默认会话
            importance_threshold: 重要性阈值

        Returns:
            生成的记忆 ID，或 None
        """
        # 按 session 取工作记忆（None → 默认会话）
        working_messages = memory_manager.working.get_context(session_id)
        if not working_messages:
            return None

        summary = self.compress_working_memory(working_messages)
        if not summary:
            if self.summary_store is not None and session_id:
                self.summary_store.create(
                    session_id=session_id,
                    content="",
                    status=FAILED,
                    error_message=_redact_error_message(
                        "Summary generation returned no content"
                    ),
                )
            return None

        if self.summary_store is not None and session_id:
            summary_row = self.summary_store.create(
                session_id=session_id,
                content=summary,
                status=READY,
            )
            memory_id = summary_row.id
        else:
            memory_id = self.save_compressed(
                episodic_memory=memory_manager.episodic,
                summary=summary,
                session_id=session_id,
                message_count=len(working_messages),
            )

        # 只清空该会话的工作记忆
        memory_manager.working.clear(session_id)

        logger.info(
            f"记忆压缩完成: session={session_id}, "
            f"{len(working_messages)} 条消息 → 摘要 (memory_id={memory_id[:8]})"
        )

        return memory_id

    def extract_key_facts(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        从对话中提取关键事实

        Args:
            messages: 消息列表

        Returns:
            提取的关键事实列表
        """
        facts = []
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")

            preference_keywords = ["喜欢", "偏好", "不要", "记得", "设置", "以后", "习惯"]
            for keyword in preference_keywords:
                if keyword in content:
                    facts.append(
                        {
                            "type": "preference",
                            "content": content[:200],
                            "keyword": keyword,
                            "role": role,
                        }
                    )
                    break

        return facts
