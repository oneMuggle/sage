"""domain 层时间工具 (2026-11-03).

只依赖 Python 标准库, 保持 domain 对 infrastructure 的零依赖.
``backend/utils/timezones.py`` 复用这些原语, 供日志 / API / 定时任务共用.
"""

from __future__ import annotations

from datetime import datetime, timezone

# domain 层默认时区字符串. 'local' 表示 "取系统本地时区, 失败回落到北京时间".
LOCAL_TIMEZONE = "local"


def utc_now() -> datetime:
    """当前 UTC 时间 (timezone-aware).

    替代已弃用的 ``datetime.utcnow()`` —— 后者返回 naive 值, 与 aware 值
    混用会抛 ``TypeError``.
    """
    return datetime.now(tz=timezone.utc)  # noqa: UP017 — datetime.UTC 是 Py 3.11+, sage-backend 跑 3.10, win7 跑 3.8


def ensure_utc(dt: datetime) -> datetime:
    """把 naive datetime 视为 UTC 并补上时区; 已带时区的原样返回.

    用于读取历史数据 —— 旧版本落库的 ISO 串没有偏移后缀, 直接参与 aware
    运算会抛 ``TypeError``.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)  # noqa: UP017 — datetime.UTC 是 Py 3.11+, sage-backend 跑 3.10, win7 跑 3.8
    return dt
