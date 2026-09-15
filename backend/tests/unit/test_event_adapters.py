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


class TestFileEventAdapterDefaultPath:
    """SAGE_USER_DATA_DIR honored by FileEventAdapter default log_path.

    Critical for Windows installs to C:\\Program Files\\Sage where the
    bundled resources/backend/data/audit/ is read-only.
    """

    def test_uses_sage_user_data_dir_when_set(self, tmp_path: Path, monkeypatch) -> None:
        from backend.adapters.out.event.file_adapter import _default_audit_log_path

        monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
        assert _default_audit_log_path() == tmp_path / "audit" / "audit.jsonl"

    def test_explicit_log_path_overrides_env(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("SAGE_USER_DATA_DIR", "/tmp/should/not/be/used")
        explicit = tmp_path / "custom.jsonl"
        adapter = FileEventAdapter(log_path=str(explicit))
        assert adapter._log_path == explicit

    def test_default_path_writes_to_sage_user_data_dir_under_env(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
        adapter = FileEventAdapter()
        adapter.emit("test_event", {"key": "value"})
        # file lands at <SAGE_USER_DATA_DIR>/audit/audit.jsonl
        target = tmp_path / "audit" / "audit.jsonl"
        assert target.exists()
        line = target.read_text(encoding="utf-8").strip()
        assert json.loads(line)["type"] == "test_event"


def test_stdout_event_adapter_doesnt_raise(capsys):
    adapter = StdoutEventAdapter(verbose=True)
    adapter.emit("test", {"foo": "bar"})
    # Just verify no exception; output is hard to capture cleanly with capsys
