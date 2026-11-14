"""Wiki 操作日志。

维护 wiki/log.md，记录 ingest/delete/rename 等操作，确定性格式可解析。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_FILENAME = "log.md"


def append_log(project_root: Path, action: str, detail: str) -> None:
    """追加一条操作日志到 wiki/log.md。

    Args:
        project_root: 项目根目录
        action: 操作类型（ingest/delete/rename/clip/research）
        detail: 操作详情（如 "raw/sources/paper.pdf -> wiki/sources/paper.md"）
    """
    log_path = project_root / "wiki" / LOG_FILENAME
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: UP017
        line = f"- [{ts}] {action}: {detail}\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        logger.warning("写入 wiki 操作日志失败: %s", exc)
