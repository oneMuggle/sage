"""检查 SAGE_USER_DATA_DIR 是否存在且可写。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register


def _resolve_user_data_dir() -> Path:
    """解析用户数据目录:env 优先,否则 ~/.sage。"""
    env = os.environ.get("SAGE_USER_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".sage"


@register
class SqliteWritableCheck:
    name = "sqlite_writable"
    description = "SAGE_USER_DATA_DIR 目录可写性"

    def run(self) -> CheckResult:
        path = _resolve_user_data_dir()

        if not path.exists():
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"目录不存在: {path}",
                f"mkdir -p {path}",
            )

        if not path.is_dir():
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"路径存在但不是目录: {path}",
                f"mkdir -p {path}",
            )

        try:
            tmp = tempfile.NamedTemporaryFile(
                dir=str(path), prefix="sage_doctor_", suffix=".tmp", delete=True
            )
            tmp.close()
        except PermissionError:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"目录不可写: {path}",
                f"chmod 755 {path}",
            )
        except OSError as exc:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"目录写入失败 ({exc.__class__.__name__}): {exc}",
                f"chmod 755 {path}",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            f"目录可写: {path}",
        )
