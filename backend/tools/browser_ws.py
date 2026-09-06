"""极简 WebSocket 客户端 —— 仅为 CDP（Chrome DevTools Protocol）服务。

为什么不用 ``websockets`` 库：CDP 命令通道必须走 WebSocket，而本机环境
当前无法从 PyPI 安装新依赖（且 Win7 py3.8 通道要同步加依赖）。CDP 对
WS 的用法极窄 —— localhost 明文、纯文本 JSON 帧、单连接一问一答 ——
用 stdlib（socket/base64/hashlib/struct）实现这个子集更可控：

- 握手：RFC 6455 标准 Upgrade + Sec-WebSocket-Key/Accept 校验；
- 发送：客户端帧必须掩码（RFC 强制），只发 FIN 文本帧；
- 接收：处理分片（continuation）、Ping→Pong、Close；不支持的二进制帧
  显式报错（CDP 不会发）；
- 帧长度三级（7bit/16bit/64bit），上限 64 MiB 防内存失控。

仅限 ``ws://127.0.0.1`` —— 本模块拒绝任何非回环地址（CDP 端口暴露到
非回环网络是教科书级危险操作）。
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
from typing import Optional

#: 单条消息上限（CDP 截图/快照可能到 MB 级，64 MiB 足够宽裕）
MAX_MESSAGE_BYTES = 64 * 1024 * 1024

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_OP_TEXT = 0x1
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


class WebSocketError(RuntimeError):
    """WS 握手/帧协议层错误。"""


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    """读满 count 字节（recv 可能短读）。"""
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise WebSocketError("连接在对端关闭")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def ws_connect(host: str, port: int, path: str, timeout: float = 15.0) -> socket.socket:
    """连接 WS 端点并完成握手；返回处于帧模式的阻塞 socket。

    仅接受回环地址 —— CDP 端口绝不暴露到非回环网络。
    """
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise WebSocketError(f"拒绝连接非回环地址: {host}（CDP 仅限 localhost）")
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))

    # 读握手响应头（到 \r\n\r\n 为止；CDP 握手响应无 body）
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise WebSocketError("握手阶段连接关闭")
        buffer += chunk
        if len(buffer) > 64 * 1024:
            raise WebSocketError("握手响应头异常过大")
    header, _, rest = buffer.partition(b"\r\n\r\n")
    status_line = header.split(b"\r\n", 1)[0].decode("latin-1")
    if " 101 " not in status_line:
        raise WebSocketError(f"WS 握手被拒绝: {status_line}")
    accept = base64.b64encode(
        hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
    ).decode()
    if accept not in header.decode("latin-1"):
        raise WebSocketError("Sec-WebSocket-Accept 校验失败")
    if rest:
        # 理论上 CDP 握手后不会立即有帧；有则说明对端行为异常，直接报错
        raise WebSocketError("握手响应携带意外数据")
    return sock


def ws_send_text(sock: socket.socket, text: str) -> None:
    """发送一条 FIN 文本帧（客户端帧按 RFC 强制掩码）。"""
    payload = text.encode("utf-8")
    length = len(payload)
    if length < 126:
        header = struct.pack("!BB", 0x81, 0x80 | length)
    elif length < 1 << 16:
        header = struct.pack("!BBH", 0x81, 0x80 | 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 0x80 | 127, length)
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(header + mask + masked)


def _read_frame(sock: socket.socket) -> tuple:
    """读单帧 → (opcode, payload, fin)。"""
    first, second = _recv_exact(sock, 2)
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if masked:
        # RFC: 服务端帧不得掩码；CDP 遵守 —— 遇到即协议错误
        raise WebSocketError("服务端帧不应掩码")
    if length == 126:
        (length,) = struct.unpack("!H", _recv_exact(sock, 2))
    elif length == 127:
        (length,) = struct.unpack("!Q", _recv_exact(sock, 8))
    if length > MAX_MESSAGE_BYTES:
        raise WebSocketError(f"帧长度 {length} 超过上限 {MAX_MESSAGE_BYTES}")
    payload = _recv_exact(sock, length) if length else b""
    return opcode, payload, fin


def ws_send_pong(sock: socket.socket, payload: bytes) -> None:
    """响应 Ping（FIN 控制帧 + 掩码）。"""
    length = len(payload)
    if length < 126:
        header = struct.pack("!BB", 0x8A, 0x80 | length)
    else:
        header = struct.pack("!BBH", 0x8A, 0x80 | 126, length)
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(header + mask + masked)


def ws_recv_text(sock: socket.socket) -> str:
    """读一条完整文本消息（自动拼分片、应答 Ping）；Close/二进制报错。"""
    fragments: list = []
    current_opcode: Optional[int] = None
    while True:
        opcode, payload, fin = _read_frame(sock)
        if opcode == _OP_PING:
            ws_send_pong(sock, payload)
            continue
        if opcode == _OP_PONG:
            continue
        if opcode == _OP_CLOSE:
            raise WebSocketError("对端发送 Close 帧")
        if opcode in (_OP_TEXT,):
            if not fin:
                current_opcode = opcode
            fragments.append(payload)
        elif opcode == 0x0:  # continuation
            if current_opcode is None:
                raise WebSocketError("意外的 continuation 帧")
            fragments.append(payload)
        else:
            raise WebSocketError(f"不支持的帧类型 0x{opcode:x}（CDP 只发文本帧）")
        if fin and fragments:
            if current_opcode is not None:
                current_opcode = None
            return b"".join(fragments).decode("utf-8")


def ws_close(sock: socket.socket) -> None:
    """尽力关闭 socket（shutdown + close，静默）。"""
    import contextlib

    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)
    with contextlib.suppress(OSError):
        sock.close()
