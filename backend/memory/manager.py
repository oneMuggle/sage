"""
Memory Manager - 记忆管理器
统一管理三层记忆系统
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Dict, List, Optional

from backend.memory.episodic import EpisodicMemory
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory, normalize_session_id

logger = logging.getLogger(__name__)


def classify_memory_type(memory_type: str, importance: int, content: str) -> str:
    """统一的记忆分类规则（MemoryManager 与 MemoryAdapter 共用的单一事实来源）

    规则（与历史行为保持一致）：
    - 显式指定的非 auto 类型原样透传
    - importance >= 8 → semantic（高重要性事实）
    - 短内容（len < 200）且 importance < 5 → working（低重要性短期记忆）
    - 其余 → episodic

    Args:
        memory_type: 调用方声明的目标类型（'working'/'episodic'/'semantic'/'auto'）
        importance: 重要性评分 1-10
        content: 记忆内容

    Returns:
        最终落库的记忆类型
    """
    if memory_type and memory_type != "auto":
        return memory_type

    # 高重要性 → 语义记忆
    if importance >= 8:
        return "semantic"

    # 低重要性短记忆 → 工作记忆
    if len(content) < 200 and importance < 5:
        return "working"

    # 默认 → 情景记忆
    return "episodic"


class MemoryManager:
    """
    记忆管理器 - 统一管理三层记忆

    负责:
    1. 协调三层记忆的读写
    2. 记忆压缩和归档
    3. 记忆检索和召回
    4. 记忆重要性评估
    """

    def __init__(self, working: WorkingMemory, episodic: EpisodicMemory, semantic: SemanticMemory):
        """
        初始化记忆管理器

        Args:
            working: 工作记忆实例
            episodic: 情景记忆实例
            semantic: 语义记忆实例
        """
        self.working = working
        self.episodic = episodic
        self.semantic = semantic

    def remember(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        将内容存入情景记忆

        Args:
            content: 记忆内容
            metadata: 额外元数据

        Returns:
            生成的记忆 ID
        """
        importance = 5
        session_id = None
        memory_type = "conversation"

        if metadata:
            importance = metadata.get("importance", 5)
            session_id = metadata.get("session_id")
            memory_type = metadata.get("memory_type", "conversation")

        return self.episodic.save(
            content=content,
            importance=importance,
            metadata=metadata,
            session_id=session_id,
            memory_type=memory_type,
        )

    def memorize(
        self,
        content: str,
        memory_type: str = "auto",
        importance: int = 5,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> str | None:
        """
        通用记忆存储接口

        Args:
            content: 记忆内容
            memory_type: 'working' | 'episodic' | 'semantic' | 'auto'
            importance: 重要性 1-10
            tags: 标签列表
            metadata: 额外元数据
            session_id: 可选会话 ID，用于工作记忆按会话隔离 / 情景记忆关联会话

        Returns:
            记忆 ID：
            - episodic / semantic：数据库持久 ID
            - working：合成 ID ``wm:<session>:<seq>``（仅用于日志/回显，非持久主键）
        """
        # 统一分类（模块级函数，与 MemoryAdapter 同一套规则）
        resolved = classify_memory_type(memory_type, importance, content)

        if resolved == "working":
            seq = self.working.add(session_id, {"role": "system", "content": content})
            sid = self.working.resolve_session_id(session_id)
            return f"wm:{sid}:{seq}"

        elif resolved == "episodic":
            meta = dict(metadata or {})
            if tags:
                meta["tags"] = tags
            sid = session_id or meta.get("session_id")
            return self.episodic.save(
                content=content, importance=importance, metadata=meta, session_id=sid
            )

        elif resolved == "semantic":
            return self.semantic.save(content=content, summary=None, tags=tags)

        else:
            logger.warning(f"未知的记忆类型: {resolved}")
            return None

    def _classify_memory_type(self, content: str, importance: int) -> str:
        """
        自动分类记忆类型（模块级 classify_memory_type 的薄包装，向后兼容保留）

        Args:
            content: 记忆内容
            importance: 重要性评分

        Returns:
            记忆类型
        """
        return classify_memory_type("auto", importance, content)

    def recall(
        self,
        query: str,
        limit: int = 5,
        memory_types: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        检索记忆

        Args:
            query: 查询文本
            limit: 每种记忆类型的返回数量
            memory_types: 要检索的记忆类型列表，None 表示全部
            session_id: 可选会话 ID，限定工作记忆的检索范围

        Returns:
            包含各类记忆检索结果的字典
        """
        results = {"working": [], "episodic": [], "semantic": []}

        # 确定要检索的类型
        if memory_types is None:
            memory_types = ["working", "episodic", "semantic"]

        # 工作记忆 - 简单的上下文匹配（按 session 隔离）
        if "working" in memory_types:
            working_context = self.working.get_context(session_id)
            if query:
                # 在工作记忆中简单搜索
                for msg in reversed(working_context):
                    if query.lower() in msg.get("content", "").lower():
                        results["working"].append(msg)
                        if len(results["working"]) >= limit:
                            break
            else:
                results["working"] = working_context[-limit:]

        # 情景记忆 - SQLite LIKE 搜索
        if "episodic" in memory_types:
            results["episodic"] = self.episodic.search(query=query, limit=limit)

        # 语义记忆 - FTS5 全文搜索
        if "semantic" in memory_types:
            results["semantic"] = self.semantic.search(query=query, limit=limit)

        return results

    def get_context(self, limit: int = 10, session_id: Optional[str] = None) -> str:
        """
        获取上下文用于 Agent

        Args:
            limit: 上下文消息数量限制
            session_id: 可选会话 ID，限定工作记忆上下文的范围

        Returns:
            格式化的上下文字符串
        """
        parts = []

        # 获取工作记忆上下文（按 session 隔离）
        working_context = self.working.get_context(session_id, limit=limit)
        if working_context:
            parts.append("【当前对话】")
            for msg in working_context:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                parts.append(f"- [{role}]: {content[:100]}...")

        # 获取最近的 episodic 记忆
        try:
            recent_episodic = self.episodic.get_recent(limit=3)
            if recent_episodic:
                parts.append("\n【相关经历】")
                for mem in recent_episodic:
                    summary = mem.get("summary", mem.get("content", ""))[:100]
                    parts.append(f"- {summary}...")
        except Exception as e:
            logger.warning(f"获取情景记忆失败: {e}")

        # 获取最近的 semantic 记忆
        try:
            recent_semantic = self.semantic.get_recent(limit=3)
            if recent_semantic:
                parts.append("\n【相关知识】")
                for mem in recent_semantic:
                    summary = mem.get("summary", mem.get("content", ""))[:100]
                    parts.append(f"- {summary}...")
        except Exception as e:
            logger.warning(f"获取语义记忆失败: {e}")

        return "\n".join(parts) if parts else ""

    def compress(self, session_id: Optional[str] = None) -> None:
        """
        压缩指定会话的工作记忆
        生成摘要并保存到情景记忆

        Args:
            session_id: 会话 ID（None → 默认会话），仅压缩并清空该会话
        """
        messages = self.working.get_context(session_id)

        if not messages:
            return

        # 生成摘要
        summary = self.working.get_summary(session_id)

        # 将摘要存入情景记忆
        try:
            self.episodic.save(
                content=f"对话摘要: {summary}",
                importance=5,
                metadata={"source": "auto_compress", "message_count": len(messages)},
                session_id=session_id,
            )

            # 清空该会话的工作记忆
            self.working.clear(session_id)

            logger.info(
                f"工作记忆已压缩: session={normalize_session_id(session_id)}, "
                f"保存了 {len(messages)} 条消息的摘要"
            )
        except Exception as e:
            logger.error(f"压缩工作记忆失败: {e}")

    def add_to_working(self, role: str, content: str, session_id: Optional[str] = None) -> None:
        """
        添加消息到工作记忆

        Args:
            role: 角色 (user/assistant/system)
            content: 消息内容
            session_id: 可选会话 ID（None → 默认会话）
        """
        self.working.add(session_id, {"role": role, "content": content})

    def search_memories(
        self,
        query: str,
        memory_type: Optional[str] = None,
        limit: int = 20,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索记忆的统一接口

        当 memory_type 为 None 或 'working' 时，把对应会话的工作记忆条目
        并入结果，每条标记 ``memory_type='working'``、``source='working_memory'``
        （修复"工作记忆检索不可见"缺陷）。

        Args:
            query: 搜索关键词（空字符串表示不过滤工作记忆条目）
            memory_type: 可选，限定记忆类型
            limit: 返回数量限制
            session_id: 可选会话 ID，用于工作记忆隔离

        Returns:
            记忆列表
        """
        if memory_type == "episodic":
            return self.episodic.search(query, limit=limit)
        elif memory_type == "semantic":
            return self.semantic.search(query, limit=limit)

        results: List[Dict[str, Any]] = []

        # 工作记忆（memory_type 为 None 或 'working'），按 session 隔离
        if memory_type in (None, "working"):
            sid = self.working.resolve_session_id(session_id)
            for msg in self.working.get_context(session_id):
                if query and query.lower() not in msg.get("content", "").lower():
                    continue
                entry = dict(msg)
                entry.setdefault("id", f"wm:{sid}:{entry.get('seq', 0)}")
                entry["memory_type"] = "working"
                entry["source"] = "working_memory"
                results.append(entry)

        if memory_type == "working":
            return results[:limit]

        # memory_type 为 None：搜索所有持久层并与工作记忆合并
        results.extend(self.episodic.search(query, limit=limit))
        results.extend(self.semantic.search(query, limit=limit))
        return results[:limit]

    def delete_memory(self, memory_id: str, memory_type: str) -> bool:
        """
        删除记忆

        Args:
            memory_id: 记忆 ID
            memory_type: 记忆类型

        Returns:
            是否删除成功
        """
        if memory_type == "episodic":
            return self.episodic.delete(memory_id)
        elif memory_type == "semantic":
            return self.semantic.delete(memory_id)
        else:
            logger.warning(f"不支持删除记忆类型: {memory_type}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """
        获取记忆统计信息

        Returns:
            统计信息字典
        """
        stats = {
            "working": {
                "message_count": len(self.working.messages),
                "total_tokens": self.working.total_tokens,
                "session_count": len(self.working.session_ids()),
            },
            "episodic": {"total": 0},
            "semantic": {"total": 0},
        }

        with contextlib.suppress(Exception):
            stats["episodic"]["total"] = self.episodic.count()

        with contextlib.suppress(Exception):
            stats["semantic"]["total"] = self.semantic.count()

        return stats
