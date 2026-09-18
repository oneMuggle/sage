"""端口占用探测的共享原语（doctor port_* checks 用）。

Windows 上 ``SO_REUSEADDR`` 允许绑定到**已被监听**的端口（占用检测永远
「空闲」），必须用 ``SO_EXCLUSIVEADDRUSE`` 才能让 bind 在任何占用下失败；
POSIX 保持 ``SO_REUSEADDR``（TIME_WAIT 也可复用）的既有语义。
"""
from __future__ import annotations

import os
import socket
from typing import Optional, Tuple


def bind_probe(port: int) -> Tuple[bool, Optional[OSError]]:
    """尝试绑定 127.0.0.1:port。

    Returns:
        (是否空闲, 绑定失败的异常)；调用方负责返回值语义（占用提示/严重度）。
        本函数总是确保 socket 被关闭。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True, None
        except OSError as exc:
            return False, exc
    finally:
        sock.close()
