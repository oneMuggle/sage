"""Sage 异常体系（纯，零外部依赖）。

把通用业务异常从 ``backend.core.exceptions`` 复制为 domain 层的
权威定义。在 ``__init__`` 中以 ``SageBaseError`` 暴露基类名（与
P2 设计稿一致）。旧位置短期保留以避免破坏既有 import，PG2.13
统一迁出到 ``core/legacy/`` 后删除。
"""

from typing import Any


class SageBaseError(Exception):
    """Sage 所有业务异常的基类。

    Attributes:
        message: 人类可读错误描述
        code:    机器可读错误码（大写下划线）
        details: 结构化上下文（可序列化）
    """

    def __init__(
        self,
        message: str,
        code: str = "SAGE_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }

    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {self.message} - {self.details}"
        return f"[{self.code}] {self.message}"


class AgentError(SageBaseError):
    """Agent 引擎运行过程中的错误。"""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code="AGENT_ERROR", details=details)


class ToolCallError(SageBaseError):
    """工具调用异常（工具执行失败时抛出）。"""

    def __init__(
        self,
        tool_name: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        merged["tool_name"] = tool_name
        super().__init__(
            message=f"工具 '{tool_name}' 执行失败: {message}",
            code="TOOL_CALL_ERROR",
            details=merged,
        )


class MaxIterationsError(SageBaseError):
    """Agent 循环超过最大迭代次数。"""

    def __init__(
        self,
        max_iterations: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        merged["max_iterations"] = max_iterations
        super().__init__(
            message=f"Agent 循环已达到最大迭代次数 ({max_iterations})",
            code="MAX_ITERATIONS_ERROR",
            details=merged,
        )


class SageMemoryError(SageBaseError):
    """记忆系统异常。

    注意：故意命名为 SageMemoryError 而非 MemoryError，避免与 Python
    内置 ``MemoryError`` 同名造成歧义。
    """

    def __init__(
        self,
        operation: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        merged["operation"] = operation
        super().__init__(
            message=f"记忆操作 '{operation}' 失败: {message}",
            code="MEMORY_ERROR",
            details=merged,
        )


class SessionNotFoundError(SageBaseError):
    """指定的会话 ID 不存在。"""

    def __init__(
        self,
        session_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        merged["session_id"] = session_id
        super().__init__(
            message=f"会话未找到: {session_id}",
            code="SESSION_NOT_FOUND",
            details=merged,
        )


class ValidationError(SageBaseError):
    """输入数据验证失败。"""

    def __init__(
        self,
        field: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        merged["field"] = field
        super().__init__(
            message=f"验证失败 [{field}]: {message}",
            code="VALIDATION_ERROR",
            details=merged,
        )


class SecurityError(SageBaseError):
    """安全检查失败（SQL 注入、XSS 等）。"""

    def __init__(
        self,
        threat_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        merged["threat_type"] = threat_type
        super().__init__(
            message=f"安全威胁 [{threat_type}]: {message}",
            code="SECURITY_ERROR",
            details=merged,
        )
