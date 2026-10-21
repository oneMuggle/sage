"""应用服务（Use Cases）。

每个 Service 对应一个高阶业务用例，通过 ``backend.ports`` 抽象
调用外部能力，由 API 路由层在装配时注入具体 adapter 实现。
"""

from typing import Any

__all__ = ["ChatService"]


def __getattr__(name: str) -> Any:
    """惰性导出 ``ChatService``（PEP 562）。

    不能在这里 eager import：``chat_service`` → ``backend.orchestration.permission``
    → ``backend.tools`` → (tools 层的 harness 埋点) → ``backend.application.services``，
    形成加载期环，``backend.tools`` 侧会在 ``AgentAction`` 定义前就回引本包。
    惰性导出让本包只作为命名空间存在，环自然断开。
    """
    if name == "ChatService":
        from backend.application.services.chat_service import ChatService

        return ChatService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
