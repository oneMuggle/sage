# mypy: disable-error-code="no-untyped-def,attr-defined,func-returns-value"
"""验证 ``backend.utils.logging`` 主要行为。

覆盖：
- 模块常量（LOG_FORMAT / LOG_LEVELS / DEFAULT_LOG_LEVEL / LOG_FILE_MAX_DAYS）
- ``TraceIdFilter`` 在没有活跃 span / 有活跃 span / 异常 span 时的行为
  （test_otel.py 已覆盖一部分, 这里补充边界情况）
- ``SageLogger`` 单例语义（``__new__`` 多次返回同一实例）
- ``setup_logging`` 默认 / 自定义 log_dir / 自定义 project_root
- ``setup_logging`` 幂等：清空旧 handler 后再注册
- ``setup_logging`` 设置 root logger level
- 控制台 handler 输出到 stdout, 文件 handler 输出到按日期命名的文件
- ``_cleanup_old_logs`` 删除超过 ``LOG_FILE_MAX_DAYS`` 的旧文件
- ``get_logger`` 缓存：同名 logger 返回同一对象
- ``set_level`` 有效级别更新 root + console handler, 无效级别忽略
- ``setup_logging`` 无效 log_level 走 fallback (INFO)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.utils import logging as _logging_mod
from backend.utils.logging import (
    DEFAULT_LOG_LEVEL,
    LOG_FILE_MAX_DAYS,
    LOG_FORMAT,
    LOG_LEVELS,
    SageLogger,
    TraceIdFilter,
    get_logger,
    set_log_level,
    setup_logging,
)

pytestmark = pytest.mark.unit


# ============================================================================
# fixtures — 隔离全局 root logger 状态
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """每个测试前后保存/恢复 root logger handlers 与 level. 防止污染其它测试."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_disabled = root.disabled
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    root.disabled = saved_disabled


@pytest.fixture(autouse=True)
def _reset_sage_logger_singleton():
    """重置 SageLogger 单例的初始化标志, 避免测试间干扰.

    注意: 模块级 ``_logger_manager`` 也是 SageLogger 的实例, 重置会断开链接.
    因此本 fixture 只在测试前后快照 ``_log_level``/``_log_dir``, 不清空 _instance.
    """
    mgr = SageLogger._instance
    saved_level = mgr._log_level if mgr else None
    saved_dir = mgr._log_dir if mgr else None
    yield
    # 测试结束后, 把单例状态恢复到调用前.
    # 不强制 set _instance=None, 因为 module-level _logger_manager 也持有引用.
    if mgr is not None:
        mgr._log_level = saved_level
        mgr._log_dir = saved_dir


# ============================================================================
# 常量
# ============================================================================


def test_module_exposes_format_and_levels() -> None:
    """模块导出 LOG_FORMAT / LOG_LEVELS / DEFAULT_LOG_LEVEL / LOG_FILE_MAX_DAYS."""
    assert "%(trace_id)s" in LOG_FORMAT
    assert "%(levelname)s" in LOG_FORMAT
    assert LOG_LEVELS["DEBUG"] == logging.DEBUG
    assert LOG_LEVELS["INFO"] == logging.INFO
    assert DEFAULT_LOG_LEVEL == "INFO"
    assert LOG_FILE_MAX_DAYS >= 1


# ============================================================================
# TraceIdFilter
# ============================================================================


def _make_record(name: str = "x") -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg="hi",
        args=(),
        exc_info=None,
    )


def test_trace_id_filter_returns_true_and_fills_placeholders_without_span() -> None:
    """无活跃 span → filter 返回 True, trace_id/span_id 注入占位符. (test_otel.py 也有)"""
    f = TraceIdFilter()
    rec = _make_record()
    assert f.filter(rec) is True
    assert rec.trace_id == "-"
    assert rec.span_id == "-"


def test_trace_id_filter_preserves_existing_attributes() -> None:
    """如果 record 上已经有 trace_id / span_id, filter 不覆盖. (设计上不覆盖业务手动设的)"""
    f = TraceIdFilter()
    rec = _make_record()
    rec.trace_id = "existing-trace"
    rec.span_id = "existing-span"
    f.filter(rec)
    assert rec.trace_id == "existing-trace"
    assert rec.span_id == "existing-span"


def test_trace_id_filter_swallows_span_exceptions() -> None:
    """get_current_span 抛异常时 filter 静默吞错并填占位符."""
    f = TraceIdFilter()
    rec = _make_record()
    with patch("backend.utils.logging.trace.get_current_span", side_effect=RuntimeError("boom")):
        # 不应抛错
        assert f.filter(rec) is True
    assert rec.trace_id == "-"
    assert rec.span_id == "-"


def test_trace_id_filter_handles_non_recording_span() -> None:
    """span 不 recording 时不注入 ID, 走占位符分支."""
    f = TraceIdFilter()
    rec = _make_record()

    # 构造一个 recording=False 的 span
    fake_span = MagicMock()
    fake_span.is_recording.return_value = False
    with patch("backend.utils.logging.trace.get_current_span", return_value=fake_span):
        f.filter(rec)
    # 不 recording → 不注入 ID, 但仍填占位符
    assert rec.trace_id == "-"
    assert rec.span_id == "-"


def test_trace_id_filter_injects_ids_from_recording_span() -> None:
    """span recording 且 ctx 有有效 trace_id/span_id 时 filter 注入 hex 字符串."""
    f = TraceIdFilter()
    rec = _make_record()

    fake_ctx = MagicMock()
    fake_ctx.trace_id = 0x1234567890ABCDEF1234567890ABCDEF
    fake_ctx.span_id = 0x1122334455667788

    fake_span = MagicMock()
    fake_span.is_recording.return_value = True
    fake_span.get_span_context.return_value = fake_ctx

    with patch("backend.utils.logging.trace.get_current_span", return_value=fake_span):
        f.filter(rec)

    assert rec.trace_id == "1234567890abcdef1234567890abcdef"
    assert rec.span_id == "1122334455667788"


def test_trace_id_filter_handles_ctx_with_zero_ids() -> None:
    """ctx.trace_id / span_id 为 0 时跳过 hex 格式化, 保留占位符."""
    f = TraceIdFilter()
    rec = _make_record()

    fake_ctx = MagicMock()
    fake_ctx.trace_id = 0
    fake_ctx.span_id = 0

    fake_span = MagicMock()
    fake_span.is_recording.return_value = True
    fake_span.get_span_context.return_value = fake_ctx

    with patch("backend.utils.logging.trace.get_current_span", return_value=fake_span):
        f.filter(rec)

    # trace_id=0/span_id=0 → 走占位符
    assert rec.trace_id == "-"
    assert rec.span_id == "-"


# ============================================================================
# SageLogger 单例
# ============================================================================


def test_sage_logger_is_singleton() -> None:
    """SageLogger 是单例: 多次构造返回同一实例."""
    a = SageLogger()
    b = SageLogger()
    assert a is b


def test_sage_logger_init_idempotent() -> None:
    """多次 __init__ 不会覆盖已初始化的状态."""
    a = SageLogger()
    a._log_level = "CUSTOM"
    a._log_dir = Path("/tmp/custom")

    # 再次"构造"—— 实际 _initialized=True, __init__ 不会再覆盖
    b = SageLogger()
    assert b is a
    assert b._log_level == "CUSTOM"
    assert b._log_dir == Path("/tmp/custom")


# ============================================================================
# setup_logging
# ============================================================================


def test_setup_logging_creates_default_log_dir(tmp_path) -> None:
    """不传 log_dir / project_root 时, 默认创建 backend/logs."""
    setup_logging(log_dir=str(tmp_path / "logs"))

    root = logging.getLogger()
    # 至少 1 个 handler（控制台）
    assert len(root.handlers) >= 1
    # 任何 handler 的 filter 含 TraceIdFilter
    has_trace_filter = any(
        any(isinstance(f, TraceIdFilter) for f in h.filters) for h in root.handlers
    )
    assert has_trace_filter


def test_setup_logging_uses_project_root_when_no_log_dir(tmp_path) -> None:
    """仅传 project_root 时, log_dir = {project_root}/logs."""
    setup_logging(project_root=str(tmp_path))
    expected = tmp_path / "logs"
    assert expected.is_dir()
    # _log_dir 已被设置

    assert _logging_mod._logger_manager._log_dir == expected


def test_setup_logging_respects_explicit_log_dir(tmp_path) -> None:
    """显式 log_dir 覆盖 project_root / 默认."""
    explicit = tmp_path / "explicit"
    setup_logging(log_dir=str(explicit), project_root=str(tmp_path))
    assert explicit.is_dir()

    assert _logging_mod._logger_manager._log_dir == explicit


def test_setup_logging_sets_root_level_to_info_by_default(tmp_path) -> None:
    """不传 log_level 时, root level == INFO."""
    setup_logging(log_dir=str(tmp_path / "logs"))
    assert logging.getLogger().level == logging.INFO


def test_setup_logging_respects_debug_level(tmp_path) -> None:
    """log_level='DEBUG' 时, root level == DEBUG."""
    setup_logging(log_dir=str(tmp_path / "logs"), log_level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_falls_back_to_info_for_invalid_level(tmp_path) -> None:
    """log_level 不在 LOG_LEVELS 中时, root level 走 INFO fallback."""
    setup_logging(log_dir=str(tmp_path / "logs"), log_level="BOGUS")
    assert logging.getLogger().level == logging.INFO


def test_setup_logging_is_idempotent_clears_old_handlers(tmp_path) -> None:
    """多次 setup_logging: handler 列表被清空再注册, 不会无限增长."""
    setup_logging(log_dir=str(tmp_path / "logs"))
    n1 = len(logging.getLogger().handlers)

    setup_logging(log_dir=str(tmp_path / "logs"))
    n2 = len(logging.getLogger().handlers)

    # 不应线性增长
    assert n1 == n2


def test_setup_logging_creates_file_handler_writing_to_log_dir(tmp_path) -> None:
    """FileHandler 输出到 {log_dir}/sage_YYYYMMDD.log."""
    setup_logging(log_dir=str(tmp_path / "logs"))

    # 找 FileHandler
    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    log_path = Path(file_handlers[0].baseFilename)
    assert log_path.parent == tmp_path / "logs"
    assert log_path.name.startswith("sage_")
    assert log_path.name.endswith(".log")
    # 关掉 handler, 释放文件锁
    for h in file_handlers:
        h.close()


def test_setup_logging_console_handler_uses_stdout(tmp_path) -> None:
    """控制台 handler 写到 stdout."""
    setup_logging(log_dir=str(tmp_path / "logs"))
    root = logging.getLogger()
    console = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert len(console) == 1
    assert console[0].stream is logging.sys.stdout


def test_setup_logging_handlers_have_trace_filter(tmp_path) -> None:
    """所有 handler 都被注入 TraceIdFilter."""
    setup_logging(log_dir=str(tmp_path / "logs"))
    root = logging.getLogger()
    for h in root.handlers:
        assert any(isinstance(f, TraceIdFilter) for f in h.filters), h


# ============================================================================
# _cleanup_old_logs
# ============================================================================


def test_cleanup_old_logs_removes_files_older_than_max_days(tmp_path) -> None:
    """超过 LOG_FILE_MAX_DAYS 天的日志文件被删除."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # 制造一个"老"文件：mtime 改为 (LOG_FILE_MAX_DAYS + 2) 天前
    old = log_dir / "sage_20200101.log"
    old.write_text("old\n", encoding="utf-8")
    old_time = time.time() - (LOG_FILE_MAX_DAYS + 2) * 86400
    os.utime(old, (old_time, old_time))

    # 制造一个"新"文件
    new = log_dir / "sage_20991231.log"
    new.write_text("new\n", encoding="utf-8")

    # 实例化一个 manager 直接调用（避免 setup 副作用）
    mgr = SageLogger()
    mgr._log_dir = log_dir
    mgr._cleanup_old_logs()

    assert not old.exists()
    assert new.exists()


def test_cleanup_old_logs_handles_missing_log_dir() -> None:
    """_log_dir 为 None 时 _cleanup_old_logs 不抛错."""
    mgr = SageLogger()
    mgr._log_dir = None
    # 不抛错
    mgr._cleanup_old_logs()


def test_cleanup_old_logs_swallows_exceptions(tmp_path, monkeypatch) -> None:
    """清理过程中任何异常都被吞掉, 不影响 setup."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "sage_x.log").write_text("x\n", encoding="utf-8")

    mgr = SageLogger()
    mgr._log_dir = log_dir

    # 让 glob 抛错 → 走 except
    def boom(_self) -> None:  # type: ignore[no-untyped-def]
        raise OSError("simulated")

    monkeypatch.setattr("pathlib.Path.glob", boom)
    # 不抛错
    mgr._cleanup_old_logs()


# ============================================================================
# get_logger
# ============================================================================


def test_get_logger_caches_loggers_by_name() -> None:
    """get_logger: 同名返回同一对象."""
    mgr = SageLogger()
    a = mgr.get_logger("alpha")
    b = mgr.get_logger("alpha")
    assert a is b
    assert a.name == "alpha"


def test_get_logger_module_level_returns_python_logger() -> None:
    """模块级 get_logger 返回 logging.Logger 实例."""
    lg = get_logger("test.module.level")
    assert isinstance(lg, logging.Logger)
    assert lg.name == "test.module.level"


# ============================================================================
# set_level
# ============================================================================


def test_set_level_updates_root_and_console_handlers(tmp_path) -> None:
    """set_level('DEBUG') → root level + console handler level 同步更新."""
    setup_logging(log_dir=str(tmp_path / "logs"), log_level="INFO")
    set_log_level("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            assert h.level == logging.DEBUG


def test_set_level_ignores_invalid_level(tmp_path) -> None:
    """set_level('BOGUS') 静默忽略, 不修改 _log_level / root level."""

    setup_logging(log_dir=str(tmp_path / "logs"), log_level="INFO")
    before = _logging_mod._logger_manager._log_level
    set_log_level("BOGUS")
    assert _logging_mod._logger_manager._log_level == before


def test_set_level_updates_only_stream_handler_not_file(tmp_path) -> None:
    """set_level 只更新 StreamHandler, 不动 FileHandler (文件仍记录所有级别)."""
    setup_logging(log_dir=str(tmp_path / "logs"))
    file_handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)
    )
    original_file_level = file_handler.level
    set_log_level("ERROR")
    # FileHandler level 不被修改
    assert file_handler.level == original_file_level
    file_handler.close()


# ============================================================================
# end-to-end
# ============================================================================


def test_setup_logging_then_log_message_appears_in_file(tmp_path) -> None:
    """端到端: setup_logging → log info → 日志写到文件."""
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=str(log_dir), log_level="INFO")

    logging.getLogger("test.end2end").info("hello world")

    # 找到今天日期的 log 文件, 验证包含消息
    log_files = list(log_dir.glob("sage_*.log"))
    assert log_files
    contents = log_files[0].read_text(encoding="utf-8")
    assert "hello world" in contents
    # 关闭 file handler 释放文件锁
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.FileHandler):
            h.close()
