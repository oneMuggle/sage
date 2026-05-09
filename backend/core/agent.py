"""
SageAgent - 核心对话引擎
基于 ReAct 模式的 Agent 实现
"""
import json
import time
import uuid
import logging
from typing import List, Dict, Any, Optional, Callable

from backend.data.session_repo import SessionRepository
from backend.data.database import get_database
from backend.memory import WorkingMemory, EpisodicMemory, SemanticMemory, MemoryManager
from backend.tools import ToolRegistry, register_all_tools

logger = logging.getLogger(__name__)


class SageAgent:
    """
    Sage 对话引擎
    
    负责:
    - 管理对话循环
    - 调用工具
    - 维护上下文
    """
    
    def __init__(self):
        self.session_repo = SessionRepository()
        self._interrupted = False
        self._current_session_id: Optional[str] = None
        
        # 初始化记忆系统
        db = get_database()
        working = WorkingMemory(max_size=20, max_tokens=4000)
        episodic = EpisodicMemory(db)
        semantic = SemanticMemory(db)
        self.memory_manager = MemoryManager(working, episodic, semantic)
        
        # 初始化工具注册表
        self.tool_registry = ToolRegistry()
        register_all_tools(self.tool_registry)
        logger.info("工具注册表初始化完成，已注册 {} 个工具".format(len(self.tool_registry.list())))
    
    async def chat(self, session_id: str, message: str) -> Dict[str, Any]:
        """
        处理用户消息
        
        Args:
            session_id: 会话 ID
            message: 用户消息
            
        Returns:
            包含 message 和 session 的字典
        """
        self._current_session_id = session_id
        self._interrupted = False
        
        # 创建用户消息
        now = int(time.time() * 1000)
        user_message = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "role": "user",
            "content": message,
            "created_at": now,
        }
        
        # 对话前：获取记忆上下文
        memory_context = self.memory_manager.get_context(limit=10)
        
        # 将用户消息添加到工作记忆
        self.memory_manager.add_to_working("user", message)
        
        # TODO: 实现真正的 AI 对话
        # 临时返回模拟响应
        assistant_message = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "role": "assistant",
            "content": f"收到消息: {message}\n\n(Agent 尚未完全实现)",
            "created_at": int(time.time() * 1000),
            "model": "gpt-3.5-turbo",
        }
        
        # 将助手消息添加到工作记忆
        self.memory_manager.add_to_working("assistant", assistant_message["content"])
        
        # 对话后：提取关键信息存入情景记忆
        # 这里可以根据实际对话内容进行重要性评估
        self._extract_and_save_memories(session_id, user_message, assistant_message)
        
        # 更新会话
        self.session_repo.update(
            session_id,
            last_message_at=assistant_message["created_at"],
            message_count=self.session_repo.get(session_id).message_count + 2 if self.session_repo.get(session_id) else 2
        )
        
        return {
            "message": assistant_message,
            "session": self.session_repo.get(session_id).to_dict() if self.session_repo.get(session_id) else None
        }
    
    def _extract_and_save_memories(
        self,
        session_id: str,
        user_message: Dict[str, Any],
        assistant_message: Dict[str, Any]
    ) -> None:
        """
        从对话中提取关键信息并存入情景记忆
        
        Args:
            session_id: 会话 ID
            user_message: 用户消息
            assistant_message: 助手消息
        """
        # 简单的记忆提取策略：
        # 1. 如果消息较长，保存摘要
        # 2. 如果包含明确的用户偏好或设置，标记为高重要性
        
        user_content = user_message.get("content", "")
        assistant_content = assistant_message.get("content", "")
        
        # 对于较长的对话，保存到情景记忆
        if len(user_content) > 100 or len(assistant_content) > 100:
            combined_content = f"[用户]: {user_content}\n[助手]: {assistant_content}"
            importance = 5
            
            # 检测是否包含偏好或设置信息
            preference_keywords = ["喜欢", "偏好", "不要", "记得", "设置", "以后"]
            for keyword in preference_keywords:
                if keyword in user_content:
                    importance = 7
                    break
            
            self.memory_manager.remember(combined_content, {
                "session_id": session_id,
                "importance": importance,
                "memory_type": "conversation"
            })
    
    async def run_loop(self, messages: List[Dict[str, Any]]) -> str:
        """
        运行 Agent 循环
        
        Args:
            messages: 消息历史
            
        Returns:
            Agent 响应
        """
        # TODO: 实现 ReAct 循环
        # 临时返回模拟响应
        return "Agent 循环尚未实现"
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            
        Returns:
            工具执行结果
        """
        tool = self.tool_registry.get(tool_name)
        if tool is None:
            return {
                "success": False,
                "error": f"工具不存在: {tool_name}"
            }
        
        try:
            result = tool.execute(**parameters)
            return result.to_dict()
        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, error: {str(e)}")
            return {
                "success": False,
                "error": f"工具执行失败: {str(e)}"
            }
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有可用工具的 Schema
        
        Returns:
            工具 Schema 列表
        """
        return self.tool_registry.get_schemas_for_llm()
    
    def interrupt(self):
        """中断当前 Agent 操作"""
        self._interrupted = True
        print("Agent 被中断")
    
    def is_interrupted(self) -> bool:
        """检查是否被中断"""
        return self._interrupted
    
    def reset_interrupt(self):
        """重置中断状态"""
        self._interrupted = False
