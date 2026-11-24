"""MinerU 客户端错误类型（code 语义对齐服务端 error.code）。"""

from __future__ import annotations

from typing import Optional


class MineruError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        param: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.param = param
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


class MineruConfigError(MineruError):
    """本机配置缺失/被禁用（不发起网络请求）。"""


class MineruAuthError(MineruError):
    """服务端要求鉴权，但 key 缺失或无效。"""


class MineruUnavailableError(MineruError):
    """传输层不可达（DNS/连接/读超时等）。"""


class MineruTimeoutError(MineruError):
    """任务级墙钟超时（已尝试 cancel）。"""


class MineruRemoteError(MineruError):
    """服务端返回的 4xx/5xx 或任务失败。"""
