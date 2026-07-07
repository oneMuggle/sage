"""
Agent Orchestrator - 多Agent协作编排
基于 Supervisor + Shared Blackboard 模式
"""

from __future__ import annotations
from typing import Dict, List, Optional

import asyncio
import json
import logging
import time
from enum import Enum
from typing import Any

from backend.agents.profiles import AgentProfile
from backend.core.legacy.llm_client import LLMClient
from backend.data.blackboard_repo import BlackboardRepo

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """用户意图分类"""

    GENERAL = "general"  # 一般对话
    RESEARCH = "research"  # 研究/信息收集
    CODING = "coding"  # 代码相关
    MEMORY = "memory"  # 记忆管理
    MULTI_STEP = "multi_step"  # 多步骤复杂任务


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
        self, session_id: str, user_message: str, history: Optional[List[Dict[str, Any]]] = None
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
            result = await self._execute_agent_task(session_id, agent_id, user_message, history)

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
            Intent.CODING: [
                "代码",
                "编程",
                "debug",
                "bug",
                "写代码",
                "code",
                "program",
                "函数",
                "类",
            ],
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

                response = await self.llm_client.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ]
                )

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
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        执行单个 Agent 任务

        阶段 2: 改为调用真实 SageAgent.run_loop (不再直接调 LLM),
        让 profile 的 system_prompt / tools / max_iterations 真正生效。

        Args:
            session_id: 会话 ID
            agent_id: Agent ID
            message: 用户消息
            history: 对话历史

        Returns:
            Agent 执行结果
        """
        from backend.core.legacy.agent import SageAgent

        # 从 orchestrator 的 llm_client 提取 config dict 传给 SageAgent
        # (SageAgent 接受 llm_config dict, 不接受 LLMClient 实例)
        # 注意: 测试场景下 llm_client 可能是 MagicMock, 需要检查属性是否为真实字符串
        llm_config_dict = None
        if self.llm_client and hasattr(self.llm_client, "config"):
            cfg = self.llm_client.config
            base_url = getattr(cfg, "base_url", None)
            # 只提取真实字符串配置, 跳过 MagicMock 等测试对象
            if isinstance(base_url, str) or base_url is None:
                llm_config_dict = {
                    "provider": getattr(cfg, "provider", "custom"),
                    "api_key": getattr(cfg, "api_key", None),
                    "base_url": base_url,
                    "model": getattr(cfg, "model", "gpt-3.5-turbo"),
                    "temperature": getattr(cfg, "temperature", 0.7),
                }

        # 检查 agent 是否存在且启用 (通过 SageAgent 内部 get_enabled_agent)
        # 如果禁用/不存在, SageAgent(agent_id=...) 会 profile=None 回退默认
        agent = SageAgent(agent_id=agent_id, llm_config=llm_config_dict)

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

        # 构造 messages 列表 (system prompt 由调用方构造, run_loop 不修改)
        system_prompt = (
            agent.profile.get("system_prompt", "你是 Sage，一个智能 AI 助手。")
            if agent.profile
            else "你是 Sage，一个智能 AI 助手。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]

        # 调用真实 SageAgent.run_loop, 收集事件流
        response_parts = []
        try:
            async for evt in agent.run_loop(messages):
                # 收集 DONE 事件的 content 作为最终响应
                if evt.state.value == "done" and evt.content:
                    response_parts.append(evt.content)
                elif evt.state.value == "failed" and evt.error:
                    response_parts.append(f"[Agent failed: {evt.error}]")
        except Exception as e:
            logger.error(f"Agent run_loop 失败 ({agent_id}): {e}")
            response_parts.append(f"[Agent error: {e}]")

        response = "\n".join(response_parts) if response_parts else "[无响应]"

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
        self, session_id: str, message: str, history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行多步骤任务

        阶段 3: 用 asyncio.gather 并行执行子任务 (而非串行),
        错误隔离 — 单个子任务失败不影响其他。

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

        if not subtasks:
            # 边界: 空子任务列表直接调 aggregate (保持行为一致)
            final_response = await self._aggregate_results(message, [])
            return {
                "agent_id": "multi_step",
                "response": final_response,
                "subtasks": [],
            }

        # 2. 并行执行所有子任务 (asyncio.gather + return_exceptions=True)
        tasks = []
        for subtask in subtasks:
            agent_id = self._select_agent(Intent(subtask.get("intent", "general")))
            tasks.append(
                self._execute_agent_task(session_id, agent_id, subtask["description"], history)
            )

        results_or_errors = await asyncio.gather(*tasks, return_exceptions=True)

        # 3. 错误隔离: 单个子任务失败不影响其他
        results = []
        for subtask, result in zip(subtasks, results_or_errors, strict=False):
            if isinstance(result, Exception):
                logger.error(f"子任务失败 ({subtask.get('description', '?')}): {result}")
                results.append(
                    {
                        "subtask": subtask,
                        "result": {
                            "agent_id": self._select_agent(
                                Intent(subtask.get("intent", "general"))
                            ),
                            "response": f"[子任务失败: {result}]",
                            "error": str(result),
                        },
                    }
                )
            else:
                results.append({"subtask": subtask, "result": result})

        # 4. 聚合结果
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

                response = await self.llm_client.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ]
                )

                subtasks = json.loads(response.content)
                if isinstance(subtasks, list) and len(subtasks) > 0:
                    return subtasks
            except Exception as e:
                logger.warning(f"任务拆解失败: {e}")

        return [{"intent": "general", "description": message}]

    async def _aggregate_results(self, original_message: str, results: List[Dict[str, Any]]) -> str:
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

                response = await self.llm_client.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                )
                return response.content
            except Exception as e:
                logger.warning(f"结果聚合失败: {e}")

        parts = []
        for i, r in enumerate(results):
            response = r["result"].get("response", "")
            parts.append(f"【子任务 {i+1}】\n{response}")
        return "\n\n".join(parts)

    async def _run_agent_llm(
        self, agent: AgentProfile, message: str, history: Optional[List[Dict[str, Any]]] = None
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

    def _summarize_history(self, history: Optional[List[Dict[str, Any]]] = None) -> str:
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
