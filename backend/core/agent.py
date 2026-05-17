"""
SageAgent - 核心对话引擎
基于 ReAct 模式的 Agent 实现
"""
import json
import time
import uuid
import logging
import hashlib
from typing import List, Dict, Any, Optional, Callable
from collections import deque
from threading import Lock

from backend.data.session_repo import SessionRepository
from backend.data.database import get_database
from backend.memory import WorkingMemory, EpisodicMemory, SemanticMemory, MemoryManager, ConsolidationPipeline
from backend.tools import ToolRegistry, register_all_tools
from backend.core.exceptions import AgentError, ToolCallError, handle_sage_error
from backend.core.llm_client import LLMClient, LLMConfig, LLMResponse

logger = logging.getLogger(__name__)


class QueryCache:
    """
    简单内存缓存
    最近查询结果缓存，TTL=5分钟
    """
    
    def __init__(self, ttl: int = 300, max_size: int = 100):
        """
        初始化缓存
        
        Args:
            ttl: 缓存生存时间（秒），默认5分钟
            max_size: 缓存最大条目数
        """
        self.ttl = ttl
        self.max_size = max_size
        self._cache: deque = deque(maxlen=max_size)
        self._lock = Lock()
    
    def _generate_key(self, session_id: str, message: str) -> str:
        """
        生成缓存键
        
        Args:
            session_id: 会话ID
            message: 消息内容
            
        Returns:
            缓存键的哈希值
        """
        key_str = f"{session_id}:{message}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, session_id: str, message: str) -> Optional[Dict[str, Any]]:
        """
        获取缓存结果
        
        Args:
            session_id: 会话ID
            message: 消息内容
            
        Returns:
            缓存结果，如果不存在或已过期返回None
        """
        key = self._generate_key(session_id, message)
        
        with self._lock:
            for item in self._cache:
                if item["key"] == key:
                    # 检查是否过期
                    if time.time() - item["timestamp"] < self.ttl:
                        logger.debug(f"缓存命中: {key[:8]}...")
                        return item["result"]
                    else:
                        # 已过期，移除
                        self._cache.remove(item)
                        break
        return None
    
    def set(self, session_id: str, message: str, result: Dict[str, Any]) -> None:
        """
        设置缓存
        
        Args:
            session_id: 会话ID
            message: 消息内容
            result: 结果数据
        """
        key = self._generate_key(session_id, message)
        
        with self._lock:
            # 移除已存在的相同键
            self._cache = deque(
                (item for item in self._cache if item["key"] != key),
                maxlen=self.max_size
            )
            
            # 添加新条目
            self._cache.append({
                "key": key,
                "session_id": session_id,
                "message": message,
                "result": result,
                "timestamp": time.time()
            })
    
    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
    
    def cleanup(self) -> int:
        """
        清理过期缓存
        
        Returns:
            清理的条目数
        """
        now = time.time()
        removed = 0
        
        with self._lock:
            original_len = len(self._cache)
            self._cache = deque(
                (item for item in self._cache if now - item["timestamp"] < self.ttl),
                maxlen=self.max_size
            )
            removed = original_len - len(self._cache)
        
        if removed > 0:
            logger.debug(f"清理了 {removed} 个过期缓存条目")
        
        return removed


class SageAgent:
    """
    Sage 对话引擎

    负责:
    - 管理对话循环
    - 调用 LLM
    - 调用工具
    - 维护上下文
    """

    def __init__(self, llm_config: Optional[Dict[str, Any]] = None):
        self.session_repo = SessionRepository()
        self._interrupted = False
        self._current_session_id: Optional[str] = None

        # 初始化查询缓存 (TTL=5分钟)
        self._cache = QueryCache(ttl=300, max_size=100)
        logger.info("查询缓存初始化完成，TTL=300秒，最大条目=100")

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

        # 初始化 LLM 客户端
        if llm_config:
            self.llm_config = LLMConfig(**llm_config)
            self.llm_client: Optional[LLMClient] = LLMClient(self.llm_config)
            logger.info("LLM 客户端已初始化: provider={}, model={}".format(
                llm_config.get("provider"), llm_config.get("model")))
        else:
            self.llm_config = None
            self.llm_client = None
            logger.warning("LLM 未配置，将使用本地模拟响应")

        # 初始化记忆压缩管道
        self.consolidation = ConsolidationPipeline(llm_client=self.llm_client)
    
    async def chat(self, session_id: str, message: str) -> Dict[str, Any]:
        """
        处理用户消息
        
        Args:
            session_id: 会话 ID
            message: 用户消息
            
        Returns:
            包含 message 和 session 的字典
        """
        try:
            # 检查缓存
            cached_result = self._cache.get(session_id, message)
            if cached_result:
                logger.info(f"返回缓存结果，会话: {session_id}")
                return cached_result
            
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
            
            # 调用 LLM
            if self.llm_client:
                assistant_content = await self._call_llm(message, memory_context)
            else:
                assistant_content = f"收到消息: {message}\n\n(LLM 未配置，使用模拟响应)"

            assistant_message = {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "role": "assistant",
                "content": assistant_content,
                "created_at": int(time.time() * 1000),
                "model": self.llm_config.model if self.llm_config else "local",
            }
            
            # 将助手消息添加到工作记忆
            self.memory_manager.add_to_working("assistant", assistant_message["content"])
            
            # 对话后：提取关键信息存入情景记忆
            self._extract_and_save_memories(session_id, user_message, assistant_message)

            # 对话后：检查是否需要压缩工作记忆
            if self.memory_manager.working.total_tokens > 3000:
                self.consolidation.consolidate(
                    self.memory_manager,
                    session_id=session_id
                )
            
            # 更新会话
            session = self.session_repo.get(session_id)
            if session:
                self.session_repo.update(
                    session_id,
                    last_message_at=assistant_message["created_at"],
                    message_count=session.message_count + 2
                )
            
            result = {
                "message": assistant_message,
                "session": session.to_dict() if session else None
            }
            
            # 存入缓存
            self._cache.set(session_id, message, result)
            
            return result
            
        except Exception as e:
            logger.error(f"chat 处理异常: {str(e)}")
            error_dict = handle_sage_error(e)
            return {
                "error": error_dict,
                "message": assistant_message if 'assistant_message' in dir() else None,
                "session": None
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
        try:
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
        except Exception as e:
            logger.warning(f"提取记忆失败: {str(e)}")
    
    async def _call_llm(self, user_message: str, memory_context: str) -> str:
        """
        调用 LLM 生成回复

        Args:
            user_message: 用户消息
            memory_context: 记忆上下文

        Returns:
            LLM 回复内容
        """
        system_prompt = "你是 Sage，一个智能 AI 助手。"
        if memory_context:
            system_prompt += "\n\n以下是相关的记忆上下文：\n" + memory_context

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            response = await self.llm_client.chat(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return f"[LLM 调用失败: {e}]"

    async def run_loop(self, messages: List[Dict[str, Any]]) -> str:
        """
        运行 Agent 循环
        
        Args:
            messages: 消息历史
            
        Returns:
            Agent 响应
        """
        try:
            # TODO: 实现 ReAct 循环
            return "Agent 循环尚未实现"
        except Exception as e:
            logger.error(f"run_loop 异常: {str(e)}")
            raise AgentError(f"Agent 循环执行失败: {str(e)}")
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            
        Returns:
            工具执行结果
        """
        try:
            tool = self.tool_registry.get(tool_name)
            if tool is None:
                raise ToolCallError(tool_name, f"工具不存在: {tool_name}")
            
            result = tool.execute(**parameters)
            return result.to_dict()
            
        except ToolCallError:
            raise
        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, error: {str(e)}")
            raise ToolCallError(tool_name, str(e))
    
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
        logger.info("Agent 被中断")
        print("Agent 被中断")
    
    def is_interrupted(self) -> bool:
        """检查是否被中断"""
        return self._interrupted
    
    def reset_interrupt(self):
        """重置中断状态"""
        self._interrupted = False
    
    def clear_cache(self) -> None:
        """清空查询缓存"""
        self._cache.clear()
        logger.info("查询缓存已清空")
    
    def cleanup_cache(self) -> int:
        """
        清理过期缓存
        
        Returns:
            清理的条目数
        """
        return self._cache.cleanup()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            缓存统计字典
        """
        return {
            "size": len(self._cache._cache),
            "max_size": self._cache.max_size,
            "ttl": self._cache.ttl
        }
