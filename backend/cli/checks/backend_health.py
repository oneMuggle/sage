"""检查 FastAPI /health 端点是否可访问且返回 ok。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from backend.cli.doctor import CheckResult, Severity, register


@register
class BackendHealthCheck:
    name = "backend_health"
    description = "FastAPI /health 端点连通性"

    TIMEOUT_SECONDS = 1

    def run(self) -> CheckResult:
        port = os.environ.get("PYTHON_BACKEND_PORT", "8765")
        url = f"http://127.0.0.1:{port}/health"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_SECONDS) as resp:
                if resp.status != 200:
                    return CheckResult(
                        self.name,
                        Severity.WARN,
                        f"后端 /health 返回非 200 (status={resp.status})",
                        "python backend/main.py",
                    )
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    return CheckResult(
                        self.name,
                        Severity.WARN,
                        f"后端 /health 返回非 JSON: {body[:80]}",
                        "python backend/main.py",
                    )
                if payload.get("status") == "ok":
                    return CheckResult(
                        self.name,
                        Severity.INFO,
                        f"后端健康检查 ok (port {port})",
                    )
                return CheckResult(
                    self.name,
                    Severity.WARN,
                    f"后端 /health status 字段不是 ok: {payload}",
                    "python backend/main.py",
                )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
            return CheckResult(
                self.name,
                Severity.WARN,
                f"backend 未启动或健康检查失败 (port {port})",
                "python backend/main.py",
            )
