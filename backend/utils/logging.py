"""
Sage 日志配置模块
使用 Python 标准库 logging，支持文件和控制台输出
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

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

# 日志文件保留天数
LOG_FILE_MAX_DAYS = 7

# 没有活动 span 时填充的占位符（避免 format 报 KeyError）
_NO_TRACE_ID = "-"


class TraceIdFilter(logging.Filter):
    """把当前 OTel span 的 ``trace_id`` / ``span_id`` 注入 log record。

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
            # 默认使用 backend/logs
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

        formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
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
        # 生成日志文件名（按日期）
        log_file = self._log_dir / f"sage_{datetime.now().strftime('%Y%m%d')}.log"

        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setLevel(logging.DEBUG)  # 文件记录所有级别

        formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
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


# 导出常用日志级别常量
DEBUG = "DEBUG"
INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"
CRITICAL = "CRITICAL"
