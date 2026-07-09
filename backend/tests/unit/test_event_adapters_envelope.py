"""M1 结构化可观测性 — 事件适配器信封化 NDJSON 单测。

- ``FileEventAdapter`` 每行含 schema + format_version（且仍保留 ts/type/payload）。
- ``StdoutEventAdapter`` 输出纯 NDJSON（整行可 ``json.loads``），不再是 ``[event] ...`` 明文。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters.out.event.file_adapter import AuditEventType, FileEventAdapter
from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter

pytestmark = pytest.mark.unit


def test_run_lifecycle_constants_exist():
    assert AuditEventType.RUN_START == "run_start"
    assert AuditEventType.TURN_START == "turn_start"
    assert AuditEventType.LLM_CALL == "llm_call"
    assert AuditEventType.TOOL_RESULT == "tool_result"
    assert AuditEventType.RUN_END == "run_end"


def test_run_lifecycle_helper_returns_5_names():
    assert AuditEventType.run_lifecycle() == [
        "run_start",
        "turn_start",
        "llm_call",
        "tool_result",
        "run_end",
    ]


def test_audit_all_still_returns_original_5():
    # 审计 spec §6.1 的 5 类不变（run-lifecycle 常量不混入 all()）
    assert len(AuditEventType.all()) == 5
    assert "run_start" not in AuditEventType.all()


def test_file_adapter_line_has_envelope(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    adapter = FileEventAdapter(log_path=str(log))

    adapter.emit("tool_invoked", {"tool": "echo"})

    line = log.read_text(encoding="utf-8").strip()
    evt = json.loads(line)
    assert evt["schema"] == "sage.agent.event"
    assert evt["format_version"] == 1
    assert evt["type"] == "tool_invoked"
    assert evt["payload"] == {"tool": "echo"}
    assert "ts" in evt  # 向后兼容旧断言


def test_stdout_adapter_emits_pure_ndjson(capsys):
    adapter = StdoutEventAdapter(verbose=True)

    adapter.emit("run_start", {"run_id": "r1"})

    out = capsys.readouterr().out.strip()
    evt = json.loads(out)  # 整行必须是合法 JSON
    assert evt["schema"] == "sage.agent.event"
    assert evt["format_version"] == 1
    assert evt["type"] == "run_start"
    assert evt["payload"] == {"run_id": "r1"}


def test_stdout_adapter_silent_when_not_verbose(capsys):
    adapter = StdoutEventAdapter(verbose=False)
    adapter.emit("run_start", {"run_id": "r1"})
    assert capsys.readouterr().out == ""
