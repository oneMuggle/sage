"""R131 — 内置审计钩子单元测试。

覆盖：JSONL 记录四键与返回 allow、默认事件名、自定义 log_dir/log_file、
超限轮转（.jsonl.1 备份、旧备份先删）、fail-open（mkdir 失败仍 allow
带 reason）、payload 字段缺省。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.hooks.builtin_audit import audit_logger

pytestmark = pytest.mark.unit


def _read_lines(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio()
async def test_audit_logger_writes_jsonl_record(tmp_path):
    log = tmp_path / "audit.jsonl"
    out = await audit_logger(
        {"hook_event_name": "post_tool_use", "tool_name": "terminal", "tool_input": {"cmd": "ls"}},
        {"log_dir": str(tmp_path)},
    )
    assert out == {"decision": "allow"}
    lines = _read_lines(log)
    assert len(lines) == 1
    record = lines[0]
    assert record["event"] == "post_tool_use"
    assert record["tool_name"] == "terminal"
    assert record["tool_input"] == {"cmd": "ls"}
    assert "T" in record["timestamp"]  # isoformat


@pytest.mark.asyncio()
async def test_default_event_name_when_missing(tmp_path):
    log = tmp_path / "audit.jsonl"
    await audit_logger({"tool_name": "t"}, {"log_dir": str(tmp_path)})
    assert _read_lines(log)[0]["event"] == "post_tool_use"


@pytest.mark.asyncio()
async def test_missing_payload_fields_default(tmp_path):
    log = tmp_path / "audit.jsonl"
    await audit_logger({}, {"log_dir": str(tmp_path)})
    record = _read_lines(log)[0]
    assert record["tool_name"] == ""
    assert record["tool_input"] is None


@pytest.mark.asyncio()
async def test_custom_log_file_name(tmp_path):
    log = tmp_path / "custom" / "my-audit.log"
    await audit_logger({"tool_name": "t"}, {"log_dir": str(tmp_path / "custom"), "log_file": "my-audit.log"})
    assert len(_read_lines(log)) == 1


@pytest.mark.asyncio()
async def test_rotation_renames_oversized_log(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text("x" * (int(0.5 * 1024 * 1024) + 10), encoding="utf-8")  # > 0.5MB
    await audit_logger(
        {"tool_name": "t"},
        {"log_dir": str(tmp_path), "max_size_mb": 0.5},
    )
    backup = tmp_path / "audit.jsonl.1"
    assert backup.exists()  # 旧文件轮转为备份
    lines = _read_lines(log)  # 新文件只含本轮记录
    assert len(lines) == 1


@pytest.mark.asyncio()
async def test_rotation_replaces_existing_backup(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text("x" * (int(0.5 * 1024 * 1024) + 10), encoding="utf-8")
    (tmp_path / "audit.jsonl.1").write_text("old-backup", encoding="utf-8")
    await audit_logger({"tool_name": "t"}, {"log_dir": str(tmp_path), "max_size_mb": 0.5})
    backup = tmp_path / "audit.jsonl.1"
    assert backup.read_text(encoding="utf-8").startswith("x")  # 备份已被新轮转替换


@pytest.mark.asyncio()
async def test_fail_open_on_unwritable_path(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    # log_dir 指向普通文件 → mkdir 失败 → fail-open，仍返回 allow
    out = await audit_logger({"tool_name": "t"}, {"log_dir": str(blocker)})
    assert out["decision"] == "allow"
    assert "audit_logger error" in out["reason"]


@pytest.mark.asyncio()
async def test_chinese_tool_input_not_escaped(tmp_path):
    log = tmp_path / "audit.jsonl"
    await audit_logger({"tool_input": {"q": "中文查询"}}, {"log_dir": str(tmp_path)})
    assert "中文查询" in log.read_text(encoding="utf-8")
