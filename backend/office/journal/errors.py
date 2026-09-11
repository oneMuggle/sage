"""JournalError 层级（继承 OfficeError）。

HTTP 映射由 backend.office.errors.office_error_to_http_status 复用，
新增子类时同时更新 office_routes 的 error envelope（offices_routes 的 mapping 段）。
"""
from __future__ import annotations

from backend.office.errors import OfficeError, OfficeParseError


class JournalError(OfficeError):
    """期刊子系统错误的基类。所有 journal 异常必须继承此类。"""


class JournalParseError(JournalError, OfficeParseError):
    """OOXML 解析失败（非法 zip / 缺 styles.xml / docx 损坏等）。

    同时继承 OfficeParseError 以复用现有的 422 HTTP 映射路径。
    """


class JournalSpecNotFoundError(JournalError):
    """SQLite / workspace 找不到指定 spec_id。"""


class JournalContentShapeError(JournalError):
    """用户提交的 content 缺必填字段或字段形状不对（生成/校验入参）。"""


class JournalPandocError(JournalError):
    """pandoc 子进程转换 .doc → .docx 失败（含超时、非零退出、stderr 不空）。"""


class JournalGenerationError(JournalError):
    """generator 内部失败（结构化 fill 阶段 / LLM 自纠阶段 / docx 落盘失败）。"""


__all__ = [
    "JournalError",
    "JournalParseError",
    "JournalSpecNotFoundError",
    "JournalContentShapeError",
    "JournalPandocError",
    "JournalGenerationError",
]
