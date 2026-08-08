"""检查当前 Python 解释器是否在 Sage conda 环境中。"""
from __future__ import annotations

import sys
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register


def _conda_env_name(exe_parts: tuple) -> str | None:
    """从解释器路径段中识别 Sage conda 环境名。

    跨平台匹配 ``envs/<name>`` 连续段对:

    - Linux: ``/anaconda3/envs/sage-backend/bin/python`` → (…, 'envs', 'sage-backend', …)
    - Windows: ``C:\\Users\\x\\anaconda3\\envs\\sage-backend-py38\\python.exe``
      → ('C:\\\\', 'Users', 'x', 'anaconda3', 'envs', 'sage-backend-py38', …)

    main 分支用硬编码前缀 ``/anaconda3/envs/...``,在 Windows 上会把合法安装
    误判为 CRITICAL;win7 分支改为按路径段匹配,两个平台都识别。
    """
    for i, part in enumerate(exe_parts[:-1]):
        if part == "envs" and exe_parts[i + 1].startswith("sage-backend"):
            return exe_parts[i + 1]
    return None


@register
class CondaEnvCheck:
    name = "conda_env"
    description = "验证当前 Python 解释器在 sage-backend conda 环境中"

    def run(self) -> CheckResult:
        exe_path = Path(sys.executable).resolve()
        exe = str(exe_path)
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"

        env_name = _conda_env_name(exe_path.parts)
        if env_name is not None:
            # py38 环境必须对应 Py3.8 解释器（用属性访问兼容单测的 SimpleNamespace mock）
            py_ver_tuple = (sys.version_info.major, sys.version_info.minor)
            if env_name.endswith("-py38") and py_ver_tuple != (3, 8):
                return CheckResult(
                    self.name,
                    Severity.CRITICAL,
                    f"Py 版本 {py_ver} 与 {env_name} 环境不匹配",
                    "conda activate sage-backend-py38",
                )
            return CheckResult(
                self.name,
                Severity.INFO,
                f"环境正确 ({py_ver})",
            )

        return CheckResult(
            self.name,
            Severity.CRITICAL,
            f"当前 Python 不在 Sage conda 环境: {exe}",
            "conda activate sage-backend",
        )
