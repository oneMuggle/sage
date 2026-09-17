"""
Sage 日志配置模块
使用 Python 标准库 logging，支持文件和控制台输出
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover — py38 compat
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from opentelemetry import trace

# 日志格式
LOG_FORMAT = "%(asctime)s [%(levelname)s] [trace=%(trace_id)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志级别
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# 默认日志级别
DEFAULT_LOG_LEVEL = "INFO"

# 默认日志时区 (2026-09-17): 'UTC' 保持历史行为.
DEFAULT_LOG_TIMEZONE = "UTC"

# 日志文件保留天数
LOG_FILE_MAX_DAYS = 7

# 没有活动 span 时填充的占位符（避免 format 报 KeyError）
_NO_TRACE_ID = "-"


class TraceIdFilter(logging.Filter):
    """把当前 OTel span 的 ``trace_id`` / ``span_id`` 注入 log record.

    给所有 handler 装上后，``LOG_FORMAT`` 中的 ``%(trace_id)s`` / ``%(span_id)s``
    就会被替换为十六进制字符串。

    设计要点：

    - **静默容错**：在 OTel 未初始化或当前无活动 span 时，
      仍然返回 ``True``（让日志继续输出），只是 trace_id/span_id
      留为 ``-``。绝不抛错吞日志。
    - **不会覆盖**：如果 record 上已有同名字段（业务代码手动设过），
      保留原值不覆盖。
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            span = trace.get_current_span()
            if span is not None and span.is_recording():
                ctx = span.get_span_context()
                if getattr(ctx, "trace_id", 0):
                    record.trace_id = format(ctx.trace_id, "032x")
                if getattr(ctx, "span_id", 0):
                    record.span_id = format(ctx.span_id, "016x")
        except Exception:  # noqa: BLE001 — 静默吞异常
            pass
        # 若没有 trace_id/span_id 属性，用占位符避免 format KeyError
        if not hasattr(record, "trace_id"):
            record.trace_id = _NO_TRACE_ID
        if not hasattr(record, "span_id"):
            record.span_id = _NO_TRACE_ID
        return True


# 日志时区 (2026-09-17): 全局当前时区设置. 由 set_log_timezone() 修改.
# 'UTC' | 'local' | IANA 时区字符串 (如 'Asia/Shanghai').
_CURRENT_LOG_TIMEZONE: str = DEFAULT_LOG_TIMEZONE


def _resolve_log_timezone(tz: str):
    """把 logTimezone 字符串解析为 tzinfo 对象. 失败回落 UTC."""
    if not tz or tz == "UTC":
        return timezone.utc
    if tz == "local":
        return None  # None 表示用本地时间 (Formatter 特殊处理)
    try:
        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001 — 非法 IANA → 回落 UTC
        return timezone.utc


class TimezoneFormatter(logging.Formatter):
    """时区感知的日志 Formatter (2026-09-17).

    通过读取模块级 ``_CURRENT_LOG_TIMEZONE`` 决定时间戳格式化的时区:

    - 'UTC': UTC 时间 (默认, 历史行为)
    - 'local': 系统本地时间
    - IANA 时区字符串: 该时区的时间

    设计要点:

    - 与 ``logging.Formatter`` 接口兼容, 无需修改调用方.
    - 时区解析失败时回落 UTC, 不会因为坏设置导致日志系统崩溃.
    - 通过 ``set_log_timezone()`` 切换后, 新生成的 record 立即使用新时区.
    """

    def __init__(self, fmt: str, datefmt: str) -> None:
        super().__init__(fmt, datefmt)
        # 初始 tzinfo 缓存. 每次 format 时若时区变更会重新解析.
        self._cached_tz_key: str = _CURRENT_LOG_TIMEZONE
        self._cached_tzinfo = _resolve_log_timezone(self._cached_tz_key)

    def formatTime(self, record, datefmt=None):  # noqa: N802 — stdlib API
        # 检查时区是否变更; 是则重新解析.
        if _CURRENT_LOG_TIMEZONE != self._cached_tz_key:
            self._cached_tz_key = _CURRENT_LOG_TIMEZONE
            self._cached_tzinfo = _resolve_log_timezone(self._cached_tz_key)

        # record.created 是 POSIX 时间戳 (秒, UTC).
        utc_dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if self._cached_tzinfo is None:
            # 'local': 转本地时区
            local_dt = utc_dt.astimezone()
        else:
            local_dt = utc_dt.astimezone(self._cached_tzinfo)
        if datefmt:
            return local_dt.strftime(datefmt)
        return local_dt.isoformat()


class SageLogger:
    """
    Sage 日志管理器
    单例模式，统一管理日志配置
    """

    _instance: Optional[SageLogger] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._loggers = {}
            self._log_dir: Optional[Path] = None
            self._log_level: str = DEFAULT_LOG_LEVEL
            self._initialized = True

    def setup(
        self,
        log_dir: Optional[str] = None,
        log_level: str = DEFAULT_LOG_LEVEL,
        project_root: Optional[str] = None,
    ) -> None:
        """
        配置日志系统

        Args:
            log_dir: 日志目录路径，默认 {project_root}/logs
            log_level: 日志级别
            project_root: 项目根目录
        """
        self._log_level = log_level

        # 确定日志目录
        if log_dir:
            self._log_dir = Path(log_dir)
        elif project_root:
            self._log_dir = Path(project_root) / "logs"
        else:
            # 默认使用 SAGE_USER_DATA_DIR/logs(per-user writable)— 当未设置
            # 时(比如 dev / 测试)退回 backend/logs,但 production 用户应通过
            # electron 注入 SAGE_USER_DATA_DIR 避免向 <C:\Program Files\Sage>
            # 这类系统保护目录写入。
            user_data_dir = os.environ.get("SAGE_USER_DATA_DIR")
            if user_data_dir:
                self._log_dir = Path(user_data_dir) / "logs"
            else:
                self._log_dir = Path(__file__).parent.parent / "logs"

        # 确保日志目录存在
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # 配置根日志器
        self._configure_root_logger()

        # 清理过期日志文件
        self._cleanup_old_logs()

    def _configure_root_logger(self) -> None:
        """配置根日志器"""
        root_logger = logging.getLogger()
        root_logger.setLevel(LOG_LEVELS.get(self._log_level, logging.INFO))

        # 清除已有的处理器
        root_logger.handlers.clear()

        # 添加控制台处理器
        console_handler = self._create_console_handler()
        root_logger.addHandler(console_handler)

        # 添加文件处理器
        file_handler = self._create_file_handler()
        root_logger.addHandler(file_handler)

    def _create_console_handler(self) -> logging.Handler:
        """
        创建控制台处理器

        Returns:
            配置好的 StreamHandler
        """
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(LOG_LEVELS.get(self._log_level, logging.INFO))

        formatter = TimezoneFormatter(LOG_FORMAT, LOG_DATE_FORMAT)
        handler.setFormatter(formatter)
        # 注入 OTel trace_id / span_id（即使没有活跃 span 也不抛错）
        handler.addFilter(TraceIdFilter())

        return handler

    def _create_file_handler(self) -> logging.Handler:
        """
        创建文件处理器

        Returns:
            配置好的 FileHandler
        """
        # 生成日志文件名（按日期）— 使用当前 logTimezone 切分.
        tz = _CURRENT_LOG_TIMEZONE
        tzinfo = _resolve_log_timezone(tz)
        if tzinfo is None:
            # local: 用本地日期
            date_str = datetime.now().strftime("%Y%m%d")
        else:
            date_str = datetime.now(tz=tzinfo).strftime("%Y%m%d")
        log_file = self._log_dir / f"sage_{date_str}.log"

        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setLevel(logging.DEBUG)  # 文件记录所有级别

        formatter = TimezoneFormatter(LOG_FORMAT, LOG_DATE_FORMAT)
        handler.setFormatter(formatter)
        handler.addFilter(TraceIdFilter())

        return handler

    def _cleanup_old_logs(self) -> None:
        """清理过期的日志文件"""
        if not self._log_dir or not self._log_dir.exists():
            return

        try:
            now = datetime.now()
            for log_file in self._log_dir.glob("sage_*.log"):
                # 获取文件修改时间
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                # 如果文件超过最大保留天数，删除
                if (now - mtime).days > LOG_FILE_MAX_DAYS:
                    log_file.unlink()
        except Exception:
            pass  # 忽略清理错误

    def get_logger(self, name: str) -> logging.Logger:
        """
        获取指定名称的日志器

        Args:
            name: 日志器名称，通常使用 __name__

        Returns:
            配置好的 Logger 实例
        """
        if name not in self._loggers:
            logger = logging.getLogger(name)
            self._loggers[name] = logger

        return self._loggers[name]

    def set_level(self, level: str) -> None:
        """
        动态设置日志级别

        Args:
            level: 日志级别字符串
        """
        if level not in LOG_LEVELS:
            return

        self._log_level = level

        # 更新根日志器级别
        root_logger = logging.getLogger()
        root_logger.setLevel(LOG_LEVELS[level])

        # 更新控制台处理器级别
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setLevel(LOG_LEVELS[level])


# 全局日志管理器实例
_logger_manager = SageLogger()


def setup_logging(
    log_dir: Optional[str] = None,
    log_level: str = DEFAULT_LOG_LEVEL,
    project_root: Optional[str] = None,
) -> None:
    """
    设置全局日志系统（便捷函数）

    Args:
        log_dir: 日志目录
        log_level: 日志级别
        project_root: 项目根目录
    """
    _logger_manager.setup(log_dir, log_level, project_root)


def get_logger(name: str) -> logging.Logger:
    """
    获取日志器（便捷函数）

    Args:
        name: 日志器名称

    Returns:
        Logger 实例
    """
    return _logger_manager.get_logger(name)


def set_log_level(level: str) -> None:
    """
    设置日志级别（便捷函数）

    Args:
        level: 日志级别
    """
    _logger_manager.set_level(level)


def set_log_timezone(tz: str) -> None:
    """设置日志时区 (2026-09-17, 便捷函数).

    Args:
        tz: 'UTC' | 'local' | IANA 时区字符串.

    Note:
        - 设置后立即生效; 新写入的日志使用新时区.
        - 不会重新创建 FileHandler; 文件名按下次创建 handler 时确定.
        - 已有 handler 的 Formatter 内部缓存会自我刷新, 无需重建.
        - 非法 IANA 时区字符串会被内部回落到 UTC, 不会抛错.
    """
    global _CURRENT_LOG_TIMEZONE
    if not tz or not isinstance(tz, str):
        return
    _CURRENT_LOG_TIMEZONE = tz


# 导出常用日志级别常量
DEBUG = "DEBUG"
INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"
CRITICAL = "CRITICAL"
