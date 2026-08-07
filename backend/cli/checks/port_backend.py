"""检查 8765 端口是否被占用(可能为孤儿 backend 进程)。"""
from __future__ import annotations

import socket

from backend.cli.doctor import CheckResult, Severity, register

PORT = 8765


@register
class PortBackendCheck:
    name = "port_backend"
    description = "8765 端口占用检测（FastAPI backend）"

    def run(self) -> CheckResult:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", PORT))
        except OSError:
            return CheckResult(
                self.name,
                Severity.WARN,
                "8765 端口被占用（可能为孤儿 backend 进程）",
                "lsof -i :8765 && kill <PID>",
            )
        finally:
            sock.close()

        return CheckResult(
            self.name,
            Severity.INFO,
            "8765 端口空闲",
        )
