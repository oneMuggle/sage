"""检查 1420 端口占用情况(Vite dev server 默认端口)。"""
from __future__ import annotations

from backend.cli.checks._ports import bind_probe
from backend.cli.doctor import CheckResult, Severity, register

PORT = 1420


@register
class PortFrontendCheck:
    name = "port_frontend"
    description = "1420 端口占用检测（Vite dev server）"

    def run(self) -> CheckResult:
        free, _exc = bind_probe(PORT)
        if not free:
            return CheckResult(
                self.name,
                Severity.INFO,
                "1420 端口已被占用（Vite dev server 可能已运行）",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            "1420 端口空闲（启动 npm run dev 会监听此端口）",
        )
