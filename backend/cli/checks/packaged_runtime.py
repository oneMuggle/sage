"""检查打包模式下的 resources 完整性（python / backend）。"""
from __future__ import annotations

from backend.cli.doctor import CheckResult, Severity, register


@register
class PackagedRuntimeCheck:
    name = "packaged_runtime"
    description = "打包模式下 resources 完整性（python / backend）"

    def run(self) -> CheckResult:
        import os

        # 仅打包模式跑此项；dev 模式跳过（返回 INFO）
        if os.environ.get("SAGE_IS_PACKAGED") != "1":
            return CheckResult(self.name, Severity.INFO, "非打包模式，跳过")
        # 通过 backendLauncher 的解析策略推断 resources 路径
        # （打包模式下 PYTHONPATH 包含 resourcesPath，可回推到根）
        pythonpath = os.environ.get("PYTHONPATH", "")
        resources = None
        for entry in pythonpath.split(os.pathsep):
            if not entry:
                continue
            # resourcesPath/backend 或 resourcesPath/sage-core 都指向 resources
            parent = entry.rstrip("/\\")
            if parent.endswith(("/backend", "\\backend", "/sage-core", "\\sage-core")):
                candidate = parent.rsplit("/backend", 1)[0].rsplit("\\backend", 1)[0]
                candidate = candidate.rsplit("/sage-core", 1)[0].rsplit("\\sage-core", 1)[0]
                resources = candidate
                break
        if resources is None:
            return CheckResult(
                self.name,
                Severity.WARN,
                "无法推断 resources 路径（PYTHONPATH 不包含 backend 或 sage-core）",
            )
        from pathlib import Path

        python_exe = Path(resources) / "python" / "python.exe"
        backend_dir = Path(resources) / "backend"
        missing = []
        if not python_exe.is_file():
            alt = Path(resources) / "python" / "python"
            if not alt.is_file():
                missing.append(f"python: {python_exe}")
        if not backend_dir.is_dir():
            missing.append(f"backend: {backend_dir}")
        # dist/index.html 在 app.asar 内，不检查
        if missing:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                "打包模式 resources 缺失: " + "; ".join(missing),
                "重装 Sage 或联系支持",
            )
        return CheckResult(self.name, Severity.INFO, "打包模式 resources 完整")
