"""时区解析工具 (2026-11-03).

统一「默认本地时区, 取不到回退北京时间」的解析逻辑, 供日志 / API / 定时任务共用.

解析链:

============  ==========================================================
输入          解析结果
============  ==========================================================
``'local'``   系统本地时区 → 北京时间 → 固定 +08:00 偏移
``'UTC'``     ``datetime.timezone.utc``
IANA 名       ``ZoneInfo(name)`` → 北京时间 → 固定 +08:00 偏移
============  ==========================================================

中国自 1991 年起不再使用夏令时, 固定 +08:00 与 ``Asia/Shanghai`` 完全等价
—— Windows 常因缺少 tzdata 导致 ``ZoneInfo`` 失败, 此时用固定偏移兜底.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo  # Python 3.9+  # py38-ok except ImportError 守卫 + backports 兜底
except ImportError:  # pragma: no cover — py38 compat
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

# 时区别名
LOCAL_TIMEZONE = "local"
UTC_TIMEZONE = "UTC"

# 北京时间回退. 中国自 1991 年起不再使用夏令时, 固定 +08:00 与 Asia/Shanghai
# 完全等价 —— ZoneInfo 在 Windows 上常因缺少 tzdata 而失败.
BEIJING_TIMEZONE_NAME = "Asia/Shanghai"
BEIJING_TIMEZONE_OFFSET = timedelta(hours=8)


def beijing_timezone() -> tzinfo:
    """北京时间 —— ZoneInfo 不可用时退回固定 +08:00 偏移."""
    try:
        return ZoneInfo(BEIJING_TIMEZONE_NAME)
    except Exception:  # noqa: BLE001 — Windows 常缺 tzdata
        return timezone(BEIJING_TIMEZONE_OFFSET)


def local_timezone() -> tzinfo:
    """系统本地时区 —— 取不到时回退北京时间.

    优先用 ``tzlocal`` (APScheduler 的传递依赖): 它返回带完整 DST 规则的
    ZoneInfo, 历史/未来日期的偏移都能算对. 拿不到时退回
    ``astimezone()`` 的当前固定偏移, 再不行才回退北京时间.
    """
    try:
        from tzlocal import get_localzone

        return get_localzone()
    except Exception:  # noqa: BLE001 — tzlocal 缺失或平台不支持
        pass
    try:
        tz = datetime.now().astimezone().tzinfo
        if tz is not None:
            return tz
    except Exception:  # noqa: BLE001 — 本地时区不可用
        pass
    return beijing_timezone()


def resolve_timezone(name: str) -> tzinfo:
    """把时区名解析为 ``tzinfo``.

    Args:
        name: ``'local'`` | ``'UTC'`` | IANA 时区名 (如 ``'Asia/Shanghai'``).

    Returns:
        对应的 ``tzinfo``; 非法输入回退北京时间, 不会抛错.
    """
    if not name or name == UTC_TIMEZONE:
        return timezone.utc  # noqa: UP017 — datetime.UTC 是 Py 3.11+, sage-backend 跑 3.10, win7 跑 3.8
    if name == LOCAL_TIMEZONE:
        return local_timezone()
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — 非法 IANA → 北京时间
        return beijing_timezone()


def local_now() -> datetime:
    """当前本地时间 (带时区偏移, timezone-aware)."""
    return datetime.now(tz=local_timezone())


def utc_now() -> datetime:
    """当前 UTC 时间 (带时区偏移, timezone-aware).

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
