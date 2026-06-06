"""应用服务（Use Cases）。

每个 Service 对应一个高阶业务用例，通过 ``backend.ports`` 抽象
调用外部能力，由 API 路由层在装配时注入具体 adapter 实现。
"""

from backend.application.services.chat_service import ChatService

__all__ = ["ChatService"]
