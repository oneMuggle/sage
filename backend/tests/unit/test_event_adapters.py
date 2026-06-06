"""验证 event adapters 骨架。"""

import json
from pathlib import Path

import pytest

from backend.adapters.out.event.file_adapter import FileEventAdapter
from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter

pytestmark = pytest.mark.unit


def test_file_event_adapter_writes_jsonl(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    adapter = FileEventAdapter(log_path=str(log))
    adapter.emit("test_event", {"key": "value"})
    adapter.emit("another", {"x": 1})

    content = log.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    assert len(lines) == 2

    e1 = json.loads(lines[0])
    assert e1["type"] == "test_event"
    assert e1["payload"] == {"key": "value"}
    assert "ts" in e1

    e2 = json.loads(lines[1])
    assert e2["type"] == "another"


def test_stdout_event_adapter_doesnt_raise(capsys):
    adapter = StdoutEventAdapter(verbose=True)
    adapter.emit("test", {"foo": "bar"})
    # Just verify no exception; output is hard to capture cleanly with capsys
