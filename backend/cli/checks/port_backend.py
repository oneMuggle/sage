"""检查 8765 端口是否被占用(可能为孤儿 backend 进程)。"""
from __future__ import annotations

import os

from backend.cli.checks._ports import bind_probe
from backend.cli.doctor import CheckResult, Severity, register

PORT = 8765


@register
class PortBackendCheck:
    name = "port_backend"
    description = "8765 端口占用检测（FastAPI backend）"

    def run(self) -> CheckResult:
        free, _exc = bind_probe(PORT)
        if not free:
            if os.name == "nt":
                hint = "netstat -ano | findstr :8765 定位 PID，taskkill /PID <pid> /F 结束"
            else:
                hint = "lsof -i :8765 && kill <PID>"
            return CheckResult(
                self.name,
                Severity.WARN,
                "8765 端口被占用（可能为孤儿 backend 进程）",
                hint,
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            "8765 端口空闲",
        )
