"""检查 backend/logs/ 目录累计大小。

诊断:NDJSON 启动日志 + backend/utils_logging.py 落盘无 TTL,长期运行用户报障
"磁盘满"频次不低。本 check 在占用 >500MB 时 WARN,>2GB 时 CRITICAL 启动阻塞。
"""
from __future__ import annotations

import os
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register

#: 阈值:超过此字节数报 WARN(单位字节)
WARN_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB
#: 阈值:超过此字节数报 CRITICAL(单位字节,启动阻塞)
CRITICAL_THRESHOLD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

#: 测试/重载用 env override
_LOG_DIR_ENV = "SAGE_LOG_DIR"


def _resolve_log_dir() -> Path:
    """解析日志目录。

    优先级(与 backend/utils/logging.py 的 setup_logging 一致):
    1. $SAGE_LOG_DIR(测试/重载用 env override)
    2. $SAGE_USER_DATA_DIR/logs(packaged Electron 注入,实际写日志位置)
    3. backend/logs/(相对此文件位置,dev/裸后端兜底)
    """
    env = os.environ.get(_LOG_DIR_ENV)
    if env:
        return Path(env)
    user_data = os.environ.get("SAGE_USER_DATA_DIR")
    if user_data:
        return Path(user_data) / "logs"
    # backend/cli/checks/<this>.py → backend/logs/
    return Path(__file__).resolve().parents[2] / "logs"


def _human_bytes(n: int) -> str:
    """人类可读字节数(复用 disk_space 的实现风格)。"""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _dir_size(path: Path) -> int:
    """递归累计目录下所有文件的大小(字节)。

    跳过不可读文件(PermissionError),但继续累计其它文件,避免单文件权限问题
    误报整目录大小。
    """
    total = 0
    for root, _dirs, files in os.walk(str(path)):
        for fname in files:
            fpath = Path(root) / fname
            try:
                total += fpath.stat().st_size
            except OSError:
                # 权限不足/文件被并发删除 → 跳过,不算入
                continue
    return total


@register
class LogDirSizeCheck:
    name = "log_dir_size"
    description = "backend/logs/ 目录累计大小(防止日志膨胀)"

    def run(self) -> CheckResult:
        path = _resolve_log_dir()

        if not path.exists():
            return CheckResult(
                self.name,
                Severity.INFO,
                f"日志目录不存在({path}),首次安装无需清理",
            )

        try:
            total = _dir_size(path)
        except OSError as exc:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"无法读取日志目录({exc.__class__.__name__}): {exc}",
                f"检查 {path} 的访问权限",
            )

        human = _human_bytes(total)
        if total >= CRITICAL_THRESHOLD_BYTES:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"日志目录膨胀 {human} (≥{_human_bytes(CRITICAL_THRESHOLD_BYTES)}): {path}",
                f"清理 {path} 下的旧日志文件,或接入 log rotation",
            )
        if total >= WARN_THRESHOLD_BYTES:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"日志目录偏大 {human} (≥{_human_bytes(WARN_THRESHOLD_BYTES)}): {path}",
                "建议配置 log rotation 或定期清理旧日志",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            f"日志目录 {human}: {path}",
        )
