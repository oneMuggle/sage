"""反馈诊断日志尾部采集。

用户在反馈里附带"最近的日志"时用。日志里可能含 API key / token 等敏感信息,
逐行过 :func:`backend.services.llm_trace.redactor.redact_text` 后才返回。

日志目录优先从 root logger 的 ``FileHandler`` 反查(与实际写入位置一致),
取不到时回退到 ``SAGE_USER_DATA_DIR/logs`` 或 ``backend/logs``。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from backend.services.llm_trace.redactor import redact_text

logger = logging.getLogger(__name__)

MAX_TAIL_LINES = 500
MAX_LINE_CHARS = 2000


def _resolve_log_dir() -> Optional[Path]:
    """定位日志目录。优先用 root logger 上的 FileHandler 反查。"""
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename).parent

    user_data_dir = os.environ.get("SAGE_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir) / "logs"
    return Path(__file__).parent.parent / "logs"


def _latest_log_file(log_dir: Path) -> Optional[Path]:
    """取目录里最新的 sage_*.log(按 mtime)。没有则 None。"""
    if not log_dir.exists():
        return None
    candidates = list(log_dir.glob("sage_*.log"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def collect_log_tail(max_lines: int = MAX_TAIL_LINES) -> str:
    """采集最近日志文件的尾部, 逐行脱敏后拼成一段文本。

    Args:
        max_lines: 最多返回多少行(尾部)。

    Returns:
        脱敏后的日志文本。找不到日志文件时返回空字符串。
    """
    max_lines = max(1, min(max_lines, MAX_TAIL_LINES))
    log_dir = _resolve_log_dir()
    if log_dir is None:
        return ""
    log_file = _latest_log_file(log_dir)
    if log_file is None:
        return ""

    try:
        raw_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        logger.warning("读取日志文件失败: %s", log_file)
        return ""

    tail = raw_lines[-max_lines:]
    return "\n".join(redact_text(line)[:MAX_LINE_CHARS] for line in tail)


def collect_log_tail_lines(max_lines: int = MAX_TAIL_LINES) -> List[str]:
    """同 :func:`collect_log_tail`, 但返回行列表(方便前端逐行渲染)。"""
    text = collect_log_tail(max_lines=max_lines)
    return text.splitlines() if text else []
