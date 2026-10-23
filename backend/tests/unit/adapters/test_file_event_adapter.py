"""R127 — 审计事件文件适配器单元测试。

覆盖：AuditEventType 常量组契约（5 类审计 + run-lifecycle 顺序）、
emit 落盘 JSONL（envelope 五键、追加写、中文原样）、显式 log_path 与
父目录自动创建、默认路径解析顺序（SAGE_USER_DATA_DIR 优先 / dev 回退）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters.out.event.file_adapter import (
    AuditEventType,
    FileEventAdapter,
    _default_audit_log_path,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# AuditEventType 常量契约
# ---------------------------------------------------------------------------


def test_audit_all_is_exactly_five_types():
    assert AuditEventType.all() == [
        "chat_message_sent",
        "chat_response_completed",
        "tool_invoked",
        "session_created",
        "settings_changed",
    ]


def test_run_lifecycle_ordered():
    lifecycle = AuditEventType.run_lifecycle()
    assert lifecycle == [
        "run_start",
        "turn_start",
        "llm_call",
        "tool_result",
        "run_end",
    ]
    assert set(lifecycle).isdisjoint(set(AuditEventType.all()))  # 不并入 all()


# ---------------------------------------------------------------------------
# emit 落盘
# ---------------------------------------------------------------------------


def _read_lines(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_emit_writes_envelope_jsonl(tmp_path):
    log = tmp_path / "audit" / "audit.jsonl"
    adapter = FileEventAdapter(log)
    adapter.emit(AuditEventType.TOOL_INVOKED, {"tool": "terminal"})

    lines = _read_lines(log)
    assert len(lines) == 1
    event = lines[0]
    assert event["type"] == "tool_invoked"
    assert event["payload"] == {"tool": "terminal"}
    for key in ("schema", "format_version", "ts"):
        assert key in event


def test_emit_appends_lines(tmp_path):
    log = tmp_path / "audit.jsonl"
    adapter = FileEventAdapter(log)
    adapter.emit(AuditEventType.SESSION_CREATED, {"session_id": "s1"})
    adapter.emit(AuditEventType.SETTINGS_CHANGED, {"key": "theme"})
    lines = _read_lines(log)
    assert [e["type"] for e in lines] == [
        "session_created",
        "settings_changed",
    ]


def test_emit_chinese_payload_raw_not_escaped(tmp_path):
    log = tmp_path / "audit.jsonl"
    adapter = FileEventAdapter(log)
    adapter.emit(AuditEventType.CHAT_MESSAGE_SENT, {"preview": "你好世界"})
    raw = log.read_text(encoding="utf-8")
    assert "你好世界" in raw  # ensure_ascii=False
    assert _read_lines(log)[0]["payload"]["preview"] == "你好世界"


def test_nested_parent_dirs_created(tmp_path):
    log = tmp_path / "deep" / "nested" / "audit.jsonl"
    FileEventAdapter(log)  # 构造即建父目录
    assert log.parent.is_dir()


# ---------------------------------------------------------------------------
# 默认路径解析顺序
# ---------------------------------------------------------------------------


def test_default_path_prefers_user_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    assert _default_audit_log_path() == tmp_path / "audit" / "audit.jsonl"


def test_default_path_falls_back_to_dev_location(monkeypatch):
    monkeypatch.delenv("SAGE_USER_DATA_DIR", raising=False)
    assert _default_audit_log_path() == Path("backend/data/audit/audit.jsonl")


def test_accepts_str_log_path(tmp_path):
    adapter = FileEventAdapter(str(tmp_path / "as-str.jsonl"))
    adapter.emit(AuditEventType.CHAT_RESPONSE_COMPLETED, {})
    assert len(_read_lines(tmp_path / "as-str.jsonl")) == 1
