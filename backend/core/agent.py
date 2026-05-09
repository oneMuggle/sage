"""
SageAgent - 核心对话引擎
基于 ReAct 模式的 Agent 实现
"""
import json
import time
import uuid
from typing import List, Dict, Any, Optional, Callable

from backend.data.session_repo import SessionRepository


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
    
    async def run_loop(self, messages: List[Dict[str, Any]]) -> str:
        """
        运行 Agent 循环
        
        Args:
            messages: 消息历史
            
        Returns:
            Agent 响应
        """
        # TODO: 实现 ReAct 循环
        return "Agent 循环尚未实现"
    
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
