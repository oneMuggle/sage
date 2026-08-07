"""检查当前 Python 解释器是否在 Sage conda 环境中。"""
from __future__ import annotations

import sys
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register


@register
class CondaEnvCheck:
    name = "conda_env"
    description = "验证当前 Python 解释器在 sage-backend conda 环境中"

    EXPECTED_PATHS = (
        # 注意：长路径（py38）必须排在短路径（默认）之前,
        # 否则 ``startswith`` 会先匹配短路径,py38 版本校验不可达。
        "/anaconda3/envs/sage-backend-py38",
        "/anaconda3/envs/sage-backend",
        "/opt/conda/envs/sage-backend",
    )

    def run(self) -> CheckResult:
        exe = str(Path(sys.executable).resolve())
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"

        for expected in self.EXPECTED_PATHS:
            if exe.startswith(expected):
                # py38 路径必须对应 Py3.8 解释器
                if "py38" in expected and py_ver != "3.8":
                    return CheckResult(
                        self.name,
                        Severity.CRITICAL,
                        f"Py 版本 {py_ver} 与 py38 环境不匹配",
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
