"""Wiki 操作日志：append_log 格式与健壮性。"""

from __future__ import annotations

import re

import pytest

from backend.wiki.operation_log import LOG_FILENAME, append_log

pytestmark = pytest.mark.unit


def test_append_log_creates_file_with_iso_utc_line(tmp_path) -> None:
    append_log(tmp_path, "ingest", "raw/sources/a.pdf -> wiki/sources/a.md")

    path = tmp_path / "wiki" / LOG_FILENAME
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert re.fullmatch(
        r"- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] "
        r"ingest: raw/sources/a\.pdf -> wiki/sources/a\.md\n",
        text,
    )


def test_append_log_appends_lines(tmp_path) -> None:
    append_log(tmp_path, "ingest", "a")
    append_log(tmp_path, "delete", "b")

    lines = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert " ingest: a" in lines[0]
    assert " delete: b" in lines[1]


def test_append_log_never_raises_on_unwritable_path(tmp_path) -> None:
    # 让 wiki/ 是一个文件而非目录，mkdir 必抛 OSError，函数须静默
    blocker = tmp_path / "wiki"
    blocker.write_text("not a dir", encoding="utf-8")

    append_log(tmp_path, "ingest", "x")  # must not raise
