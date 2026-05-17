"""
Agent Orchestrator - 多Agent协作编排
基于 Supervisor + Shared Blackboard 模式
"""
import json
import time
import logging
from typing import List, Dict, Any, Optional
from enum import Enum

from backend.agents.profiles import AgentProfile, get_agent, list_agents
from backend.data.blackboard_repo import BlackboardRepo
from backend.core.llm_client import LLMClient

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """用户意图分类"""
    GENERAL = "general"          # 一般对话
    RESEARCH = "research"        # 研究/信息收集
    CODING = "coding"            # 代码相关
    MEMORY = "memory"            # 记忆管理
    MULTI_STEP = "multi_step"    # 多步骤复杂任务


class AgentOrchestrator:
    """
    Agent 编排器

    职责:
    - 意图识别: 判断用户需求
    - 任务分发: 选择合适的 Agent
    - 结果聚合: 汇总多个 Agent 的输出
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client
        self.blackboard = BlackboardRepo()
        self._agent_cache: Dict[str, AgentProfile] = {}

    async def process_request(
        self,
        session_id: str,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        处理用户请求的主入口

        Args:
            session_id: 会话 ID
            user_message: 用户消息
            history: 对话历史

        Returns:
            处理结果
        """
        start_time = time.time()

        # 1. 意图识别
        intent = await self._classify_intent(user_message)
        logger.info(f"意图识别: {intent.value}")

        # 2. 任务分发
        if intent == Intent.MULTI_STEP:
            result = await self._execute_multi_step(session_id, user_message, history)
        else:
            agent_id = self._select_agent(intent)
            result = await self._execute_agent_task(
                session_id, agent_id, user_message, history
            )

        # 3. 记录结果
        elapsed = time.time() - start_time
        result["metadata"] = {
            "intent": intent.value,
            "agent_used": result.get("agent_id", "unknown"),
            "elapsed_ms": int(elapsed * 1000),
        }

        return result

    async def _classify_intent(self, message: str) -> Intent:
        """
        使用 LLM 进行意图分类

        Args:
            message: 用户消息

        Returns:
            意图枚举
        """
        # 关键词回退策略
        keyword_map = {
            Intent.RESEARCH: ["搜索", "查找", "研究", "调查", "search", "find", "research"],
            Intent.CODING: ["代码", "编程", "debug", "bug", "写代码", "code", "program", "函数", "类"],
            Intent.MEMORY: ["记忆", "忘记", "记住", "回顾", "memory", "forget", "remember"],
        }

        for intent, keywords in keyword_map.items():
            if any(kw in message.lower() for kw in keywords):
                return intent

        # LLM 分类
        if self.llm_client:
            try:
                system_prompt = """你是一个意图分类器。将用户消息分类为以下意图之一:
- general: 一般对话，闲聊，简单问答
- research: 需要搜索、研究、信息收集
- coding: 代码编写、调试、审查
- memory: 记忆管理，回顾，遗忘
- multi_step: 多步骤复杂任务，需要多个专业Agent协作

只回复意图名称，不要解释。"""

                response = await self.llm_client.chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ])

                intent_str = response.content.strip().lower()
                for intent in Intent:
                    if intent.value in intent_str:
                        return intent

            except Exception as e:
                logger.warning(f"LLM 意图分类失败，回退到 general: {e}")

        return Intent.GENERAL

    def _select_agent(self, intent: Intent) -> str:
        """
        根据意图选择 Agent

        Args:
            intent: 意图类型

        Returns:
            Agent ID
        """
        intent_to_agent = {
            Intent.GENERAL: "primary",
            Intent.RESEARCH: "researcher",
            Intent.CODING: "coder",
            Intent.MEMORY: "memory_manager",
        }
        return intent_to_agent.get(intent, "primary")

    async def _execute_agent_task(
        self,
        session_id: str,
        agent_id: str,
        message: str,
        history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行单个 Agent 任务

        Args:
            session_id: 会话 ID
            agent_id: Agent ID
            message: 用户消息
            history: 对话历史

        Returns:
            Agent 执行结果
        """
        agent = get_agent(agent_id)
        if not agent:
            return {"error": f"Agent not found: {agent_id}", "agent_id": agent_id}

        # 发布任务到黑板
        task_id = self.blackboard.publish(
            session_id=session_id,
            agent_name="orchestrator",
            message_type="task",
            content={
                "agent_id": agent_id,
                "message": message,
                "history_summary": self._summarize_history(history),
            },
            target_agent=agent_id,
        )

        logger.info(f"任务发布: {agent_id} (task_id={task_id})")

        # 获取 Agent 回复 (简化实现: 直接通过 LLM)
        response = await self._run_agent_llm(agent, message, history)

        # 发布结果到黑板
        self.blackboard.publish(
            session_id=session_id,
            agent_name=agent_id,
            message_type="result",
            content={"response": response},
            target_agent="orchestrator",
        )

        return {
            "agent_id": agent_id,
            "response": response,
            "task_id": task_id,
        }

    async def _execute_multi_step(
        self,
        session_id: str,
        message: str,
        history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行多步骤任务

        顺序执行: 拆解子任务 → 分发 → 聚合

        Args:
            session_id: 会话 ID
            message: 用户消息
            history: 对话历史

        Returns:
            聚合结果
        """
        # 1. 拆解子任务
        subtasks = await self._decompose_task(message)
        logger.info(f"多步骤任务拆解: {len(subtasks)} 个子任务")

        results = []
        for subtask in subtasks:
            agent_id = self._select_agent(Intent(subtask.get("intent", "general")))
            result = await self._execute_agent_task(
                session_id, agent_id, subtask["description"], history
            )
            results.append({
                "subtask": subtask,
                "result": result,
            })

        # 2. 聚合结果
        final_response = await self._aggregate_results(message, results)

        return {
            "agent_id": "multi_step",
            "response": final_response,
            "subtasks": results,
        }

    async def _decompose_task(self, message: str) -> List[Dict[str, Any]]:
        """
        将复杂任务拆解为子任务

        Args:
            message: 用户消息

        Returns:
            子任务列表
        """
        if self.llm_client:
            try:
                system_prompt = """你是一个任务规划师。将用户的复杂任务拆解为独立的子任务。
每个子任务应该是:
- general: 一般对话
- research: 研究/搜索
- coding: 代码相关
- memory: 记忆管理

回复 JSON 数组格式: [{"intent": "research", "description": "..."}, ...]
只回复 JSON，不要解释。"""

                response = await self.llm_client.chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ])

                subtasks = json.loads(response.content)
                if isinstance(subtasks, list) and len(subtasks) > 0:
                    return subtasks
            except Exception as e:
                logger.warning(f"任务拆解失败: {e}")

        # 回退: 整个任务作为单个子任务
        return [{"intent": "general", "description": message}]

    async def _aggregate_results(
        self,
        original_message: str,
        results: List[Dict[str, Any]]
    ) -> str:
        """
        聚合多个子任务的结果

        Args:
            original_message: 原始用户消息
            results: 子任务执行结果

        Returns:
            聚合后的回复
        """
        if self.llm_client:
            try:
                context_parts = []
                for i, r in enumerate(results):
                    subtask_desc = r["subtask"].get("description", "")
                    response = r["result"].get("response", "")
                    context_parts.append(f"子任务 {i+1}: {subtask_desc}\n结果: {response}")

                system_prompt = "你是一个任务协调者。将以下子任务的结果整合为一个连贯的回复。"
                user_prompt = f"原始问题: {original_message}\n\n" + "\n\n".join(context_parts)

                response = await self.llm_client.chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ])
                return response.content
            except Exception as e:
                logger.warning(f"结果聚合失败: {e}")

        # 回退: 简单拼接
        parts = []
        for i, r in enumerate(results):
            response = r["result"].get("response", "")
            parts.append(f"【子任务 {i+1}】\n{response}")
        return "\n\n".join(parts)

    async def _run_agent_llm(
        self,
        agent: AgentProfile,
        message: str,
        history: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        使用 Agent 的 LLM 配置执行对话

        Args:
            agent: Agent 配置
            message: 用户消息
            history: 对话历史

        Returns:
            LLM 回复
        """
        if not self.llm_client:
            return f"[模拟回复] {agent.name} 收到: {message}"

        try:
            messages = [
                {"role": "system", "content": agent.system_prompt},
            ]

            if history:
                for msg in history[-5:]:  # 最近5条历史
                    messages.append({"role": msg["role"], "content": msg["content"]})

            messages.append({"role": "user", "content": message})

            response = await self.llm_client.chat(messages)
            return response.content
        except Exception as e:
            logger.error(f"Agent LLM 调用失败 ({agent.id}): {e}")
            return f"[{agent.name} LLM 调用失败: {e}]"

    def _summarize_history(
        self,
        history: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        简单总结对话历史

        Args:
            history: 对话历史

        Returns:
            总结文本
        """
        if not history or len(history) == 0:
            return "无对话历史"

        recent = history[-3:]
        summaries = []
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:100]
            summaries.append(f"{role}: {content}")
        return "\n".join(summaries)
