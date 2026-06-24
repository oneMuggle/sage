"""LLM 错误领域模型（纯，零外部依赖）。

把 LLM API 调用可能出现的错误统一分类为 7 种类型，便于前端做
中文化友好提示与差异化处理。

注意：该文件由 ``backend.core.errors`` 拷贝而来，作为 domain 层的
权威定义。旧位置短期保留以避免破坏既有 import，PG2.13 阶段一并
迁出到 ``core/legacy/`` 后删除。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class LLMErrorType(str, Enum):
    """LLM 错误类型枚举。

    采用 snake_case 字符串值，便于 JSON 序列化与前端映射。
    """

    AUTH_FAILED = "auth_failed"  # HTTP 401：API Key 无效或过期
    RATE_LIMITED = "rate_limited"  # HTTP 429：请求频率超限
    SERVER_ERROR = "server_error"  # HTTP 5xx：LLM 服务端错误
    NETWORK = "network_error"  # 连接失败、DNS 失败等网络层错误
    TIMEOUT = "timeout"  # 请求超时
    PARSING = "parsing_error"  # 响应格式无法解析
    UNKNOWN = "unknown"  # 未分类错误


@dataclass
class LLMError(Exception):
    """LLM 错误异常，承载分类信息与原始上下文。

    Attributes:
        type:        错误类型
        message:     人类可读的错误描述
        status_code: HTTP 状态码（如适用）
        retry_after: 建议的重试等待秒数（仅 RATE_LIMITED 使用）
    """

    type: LLMErrorType
    message: str
    status_code: int | None = None
    retry_after: int | None = None  # 仅 RATE_LIMITED 时使用（秒）

    def __post_init__(self) -> None:
        # dataclass 不会自动调用 super().__init__，手动把 message 传给
        # Exception，让 str(err) / err.args / traceback 能正确携带信息。
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 API 响应格式。"""
        return {
            "type": self.type.value,
            "message": self.message,
            "status_code": self.status_code,
            "retry_after": self.retry_after,
        }
