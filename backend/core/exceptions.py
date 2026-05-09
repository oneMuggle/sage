"""
Sage 异常类定义
统一错误处理规范
"""

from typing import Optional, Any, Dict


class SageError(Exception):
    """
    Sage 基础异常类
    所有 Sage 相关异常的基类
    """
    
    def __init__(
        self,
        message: str,
        code: str = "SAGE_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details
        }
    
    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {self.message} - {self.details}"
        return f"[{self.code}] {self.message}"


class AgentError(SageError):
    """
    Agent 执行异常
    Agent 引擎运行过程中的错误
    """
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            code="AGENT_ERROR",
            details=details
        )


class ToolCallError(SageError):
    """
    工具调用异常
    工具执行失败时抛出
    """
    
    def __init__(
        self,
        tool_name: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["tool_name"] = tool_name
        super().__init__(
            message=f"工具 '{tool_name}' 执行失败: {message}",
            code="TOOL_CALL_ERROR",
            details=details
        )


class MaxIterationsError(SageError):
    """
    最大迭代次数异常
    Agent 循环超过最大迭代次数时抛出
    """
    
    def __init__(
        self,
        max_iterations: int,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["max_iterations"] = max_iterations
        super().__init__(
            message=f"Agent 循环已达到最大迭代次数 ({max_iterations})",
            code="MAX_ITERATIONS_ERROR",
            details=details
        )


class MemoryError(SageError):
    """
    记忆系统异常
    记忆操作失败时抛出
    """
    
    def __init__(
        self,
        operation: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["operation"] = operation
        super().__init__(
            message=f"记忆操作 '{operation}' 失败: {message}",
            code="MEMORY_ERROR",
            details=details
        )


class SessionNotFoundError(SageError):
    """
    会话未找到异常
    指定的会话 ID 不存在时抛出
    """
    
    def __init__(
        self,
        session_id: str,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["session_id"] = session_id
        super().__init__(
            message=f"会话未找到: {session_id}",
            code="SESSION_NOT_FOUND",
            details=details
        )


class ValidationError(SageError):
    """
    数据验证异常
    输入数据验证失败时抛出
    """
    
    def __init__(
        self,
        field: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["field"] = field
        super().__init__(
            message=f"验证失败 [{field}]: {message}",
            code="VALIDATION_ERROR",
            details=details
        )


class SecurityError(SageError):
    """
    安全异常
    安全检查失败时抛出 (SQL注入、XSS等)
    """
    
    def __init__(
        self,
        threat_type: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["threat_type"] = threat_type
        super().__init__(
            message=f"安全威胁 [{threat_type}]: {message}",
            code="SECURITY_ERROR",
            details=details
        )


def handle_sage_error(error: Exception) -> Dict[str, Any]:
    """
    将异常转换为统一错误格式
    
    Args:
        error: 原始异常
        
    Returns:
        统一格式的错误字典
    """
    if isinstance(error, SageError):
        return error.to_dict()
    
    # 未知异常，包装为通用错误
    return {
        "error": "INTERNAL_ERROR",
        "message": str(error),
        "details": {"type": type(error).__name__}
    }
