"""
Agent 状态机与事件流定义

用于 ReAct 循环:IDLE → THINKING → ACTING → OBSERVING → DONE/FAILED
事件流通过 FastAPI 流式响应(NDJSON)下发到前端。
"""

from __future__ import annotations
from typing import Dict, Optional

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgentState(str, Enum):
    """Agent 状态枚举。"""

    IDLE = "idle"
    THINKING = "thinking"
    # REASONING: 携带 LLM 思考/推理过程内容（reasoning_content）
    # 区别于 THINKING（仅表示"LLM 正在思考"阶段标记）
    REASONING = "reasoning"
    ACTING = "acting"
    OBSERVING = "observing"
    # I4: 流式 LLM 响应时,每个 token chunk 推一个 CONTENT_DELTA 事件,
    # 前端 appendContent 累积,实现逐字流式
    CONTENT_DELTA = "content_delta"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ToolCallRequest:
    """工具调用请求(LLM 发出)。"""

    id: str
    name: str
    arguments: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 OpenAI 工具调用格式。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class ToolCallResult:
    """工具调用结果(前端展示用)。"""

    tool_call_id: str
    content: str
    is_error: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "role": "tool",
            "content": self.content,
        }


@dataclass
class AgentEvent:
    """Agent 事件,前端通过流式响应接收。"""

    state: AgentState
    iteration: int = 0
    content: Optional[str] = None
    reasoning: Optional[str] = None  # LLM 思考/推理过程内容
    tool_call: Optional[ToolCallRequest] = None
    tool_result: Optional[ToolCallResult] = None
    error: Optional[str] = None
    agent_id: Optional[str] = None  # 当前执行 agent 的 ID(供前端显示"当前处理 agent")

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 友好的字典。"""
        d: Dict[str, Any] = {
            "state": self.state.value,
            "iteration": self.iteration,
        }
        if self.content is not None:
            d["content"] = self.content
        if self.reasoning is not None:
            d["reasoning"] = self.reasoning
        if self.tool_call is not None:
            d["tool_call"] = self.tool_call.to_dict()
        if self.tool_result is not None:
            d["tool_result"] = self.tool_result.to_dict()
        if self.error is not None:
            d["error"] = self.error
        if self.agent_id is not None:
            d["agent_id"] = self.agent_id
        return d
