"""
Agent 状态机与事件流定义

用于 ReAct 循环:IDLE → THINKING → ACTING → OBSERVING → DONE/FAILED
事件流通过 FastAPI 流式响应(NDJSON)下发到前端。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class AgentState(str, Enum):
    """Agent 状态枚举。"""

    IDLE = "idle"
    THINKING = "thinking"
    # REASONING: 携带 LLM 思考/推理过程内容（reasoning_content）
    # 区别于 THINKING（仅表示"LLM 正在思考"阶段标记）
    REASONING = "reasoning"
    # 收尾时携带累计完整 reasoning，前端应整体替换而非追加。
    REASONING_FINAL = "reasoning_final"
    ACTING = "acting"
    OBSERVING = "observing"
    # I4: 流式 LLM 响应时,每个 token chunk 推一个 CONTENT_DELTA 事件,
    # 前端 appendContent 累积,实现逐字流式
    CONTENT_DELTA = "content_delta"
    # M1 工具安全加固: 工具调用需要用户审批时,在执行前推一个
    # PERMISSION_REQUEST 事件(携带 permission_request 字段),前端渲染
    # 审批对话框并 POST /api/v1/permissions/{request_id}/answer。
    PERMISSION_REQUEST = "permission_request"
    # M2 part B: ask_user_question 工具向用户提问时,在等待应答前推一个
    # ASK_USER_QUESTION 事件(携带 user_question 字段),前端渲染
    # QuestionDialog 并 POST /api/v1/questions/{request_id}/answer。
    ASK_USER_QUESTION = "ask_user_question"
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
    # M1: state=PERMISSION_REQUEST 时携带审批请求快照(ApprovalRequest.to_dict),
    # 含 request_id / tool_name / args_summary / risk / message / created_at 字段
    permission_request: Optional[Dict[str, Any]] = None
    # M2 part B: state=ASK_USER_QUESTION 时携带提问快照(QuestionRequest.to_dict),
    # 含 request_id / question / header / options / multi_select / created_at 字段
    user_question: Optional[Dict[str, Any]] = None
    # B2 (对话阅读体验第二轮): 终稿 DONE 事件携带 LLM 的 finish_reason
    # (stop / length / tool_calls ...)。length = 触达输出上限被截断, 前端据此
    # 提示并提供"继续生成"; 同一值随终稿 assistant 行落库 (messages.finish_reason)。
    finish_reason: Optional[str] = None
    # C1 (对话阅读体验第二轮): 终稿 DONE 事件携带本次 LLM 调用的生成统计
    # 字段为输入输出 tokens、首字延迟、总耗时, 缺失项省略; 前端据此显示生成速度,
    # 同一值随终稿 assistant 行落库 (messages.generation_stats 列)。
    generation_stats: Optional[Dict[str, int]] = None

    def __post_init__(self) -> None:
        # finish_reason 只接受字符串: 测试替身 (MagicMock 响应) 等非 str 值归一为
        # None, 保证事件可 JSON 序列化、落库时 sqlite 可绑定。
        if not isinstance(self.finish_reason, str):
            self.finish_reason = None
        # generation_stats 只接受 {str: int}: 非法值同样归一为 None。
        stats = self.generation_stats
        if stats is not None and not (
            isinstance(stats, dict)
            and all(isinstance(v, int) and not isinstance(v, bool) for v in stats.values())
        ):
            self.generation_stats = None

    @staticmethod
    def generation_stats_from(response: Any) -> Optional[Dict[str, int]]:
        """从 LLMResponse 提取终稿生成统计; tokens 为 0 视为上游没有返回用量。"""
        stats: Dict[str, int] = {}
        for key in ("input_tokens", "output_tokens", "first_token_ms", "latency_ms"):
            value = getattr(response, key, None)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                continue
            if value == 0 and key.endswith("_tokens"):
                continue
            stats[key] = value
        return stats or None

    @property
    def generation_stats_json(self) -> Optional[str]:
        """generation_stats 的 JSON 文本 (落库用); 没有统计时为 None。"""
        return json.dumps(self.generation_stats) if self.generation_stats else None

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
        if self.permission_request is not None:
            d["permission_request"] = self.permission_request
        if self.user_question is not None:
            d["user_question"] = self.user_question
        if self.finish_reason is not None:
            d["finish_reason"] = self.finish_reason
        if self.generation_stats:
            d["generation_stats"] = self.generation_stats
        return d
