"""
LLM 错误类型定义

将 LLM API 调用中可能出现的错误统一分类为 7 种类型，
便于前端做中文化友好提示与差异化处理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class LLMErrorType(str, Enum):
    """LLM 错误类型枚举。

    命名采用 snake_case 字符串值，便于 JSON 序列化与前端映射。
    """

    AUTH_FAILED = "auth_failed"  # HTTP 401：API Key 无效或过期
    RATE_LIMITED = "rate_limited"  # HTTP 429：请求频率超限
    SERVER_ERROR = "server_error"  # HTTP 5xx：LLM 服务端错误
    NETWORK = "network_error"  # 连接失败、DNS 失败等网络层错误
    TIMEOUT = "timeout"  # 请求超时
    PARSING = "parsing_error"  # 响应格式无法解析
    CONTEXT_OVERFLOW = "context_overflow"  # 输入超过模型上下文窗口（需压缩后重试）
    UNKNOWN = "unknown"  # 未分类错误


@dataclass
class LLMError(Exception):
    """LLM 错误异常，承载分类信息与原始上下文。"""

    type: LLMErrorType
    message: str
    status_code: Optional[int] = None
    retry_after: Optional[int] = None  # 仅 RATE_LIMITED 时使用（秒）

    def __post_init__(self) -> None:
        # dataclass 不会自动调用 super().__init__，手动把 message 传给 Exception，
        # 让 str(err) / err.args / traceback 能正确携带信息。
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 API 响应格式。"""
        return {
            "type": self.type.value,
            "message": self.message,
            "status_code": self.status_code,
            "retry_after": self.retry_after,
        }


@dataclass
class VisionNotAvailableError(LLMError):
    """对话模型不支持视觉识别且未配置视觉理解模型时抛出。

    继承 ``LLMError`` 以便 SSE producer 的 ``except LLMError`` 能够捕获，
    通过 ``to_dict()`` 输出结构化错误并推送终态事件，避免前端永久 loading。
    """

    type: LLMErrorType = field(default=LLMErrorType.UNKNOWN, init=False, compare=False)
    status_code: Optional[int] = field(default=None, init=False, compare=False)
    retry_after: Optional[int] = field(default=None, init=False, compare=False)

    def __init__(self, message: str = "视觉识别不可用") -> None:
        super().__init__(
            type=LLMErrorType.UNKNOWN,
            message=message,
        )
