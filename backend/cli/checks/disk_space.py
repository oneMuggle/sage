"""检查用户数据目录所在分区的剩余磁盘空间。"""
from __future__ import annotations

import shutil

from backend.cli.checks.sqlite_writable import _resolve_user_data_dir
from backend.cli.doctor import CheckResult, Severity, register

# 阈值:剩余空间低于此值报 WARN(单位字节)
WARN_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB


def _human_bytes(n: int) -> str:
    """人类可读字节数。"""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


@register
class DiskSpaceCheck:
    name = "disk_space"
    description = "用户数据目录所在分区剩余空间"

    def run(self) -> CheckResult:
        path = _resolve_user_data_dir()
        target = path if path.exists() else path.parent

        try:
            usage = shutil.disk_usage(str(target))
        except OSError as exc:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"无法读取磁盘用量 ({exc.__class__.__name__}): {exc}",
                "检查路径或挂载权限",
            )

        free_human = _human_bytes(usage.free)
        if usage.free < WARN_THRESHOLD_BYTES:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"剩余空间不足 {free_human} (阈值 500MB): {path}",
                f"清理 {path} 或扩展磁盘",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            f"剩余空间 {free_human}: {path}",
        )
