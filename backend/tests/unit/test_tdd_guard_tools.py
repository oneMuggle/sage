"""Tool-layer tests for the TDD guard nudge injection.

Covers: write_file / edit_file / bash self-reporting to
``ToolPolicy.tdd_guard`` and surfacing the nudge in the tool result content
(the LLM sees the content dict serialized by ``agent.py``).
"""

from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.bash_tool import BashTool
from backend.tools.edit_tool import EditTool
from backend.tools.file_tool import WriteFileTool


class RecordingGuard:
    """Minimal TddGuard stand-in that records observations."""

    def __init__(self) -> None:
        self.calls = []

    def observe_write(self, path):
        self.calls.append(("write", path))
        return "NUDGE"

    def observe_test(self, command, exit_code):
        self.calls.append(("bash", command, exit_code))


class TestWriteToolNudge:
    def test_write_file_reports_and_nudges(self, tmp_path: Path):
        guard = RecordingGuard()
        tool = WriteFileTool(policy=ToolPolicy(tdd_guard=guard))
        target = tmp_path / "src" / "foo.py"
        target.parent.mkdir(parents=True)

        result = tool.execute(path=str(target), content="x = 1\n")

        assert result.success
        assert result.content["tdd_nudge"] == "NUDGE"
        assert ("write", str(target.resolve())) in guard.calls

    def test_write_file_without_guard_has_no_nudge(self, tmp_path: Path):
        tool = WriteFileTool(policy=ToolPolicy())
        target = tmp_path / "foo.py"

        result = tool.execute(path=str(target), content="x = 1\n")

        assert result.success
        assert "tdd_nudge" not in result.content


class TestEditToolNudge:
    def test_edit_file_reports_and_nudges(self, tmp_path: Path):
        guard = RecordingGuard()
        target = tmp_path / "foo.py"
        target.write_text("old\n", encoding="utf-8")
        tool = EditTool(policy=ToolPolicy(tdd_guard=guard))

        result = tool.execute(file_path=str(target), old_string="old", new_string="new")

        assert result.success
        assert result.content["tdd_nudge"] == "NUDGE"
        assert ("write", str(target.resolve())) in guard.calls

    def test_edit_file_without_guard_has_no_nudge(self, tmp_path: Path):
        target = tmp_path / "foo.py"
        target.write_text("old\n", encoding="utf-8")
        tool = EditTool(policy=ToolPolicy())

        result = tool.execute(file_path=str(target), old_string="old", new_string="new")

        assert result.success
        assert "tdd_nudge" not in result.content


class TestBashToolAudit:
    def test_bash_reports_command_and_exit_code(self):
        guard = RecordingGuard()
        tool = BashTool(policy=ToolPolicy(tdd_guard=guard))

        result = tool.execute(command="echo hello")

        assert result.success
        assert ("bash", "echo hello", 0) in guard.calls

    def test_bash_without_guard_does_not_report(self):
        tool = BashTool(policy=ToolPolicy())

        result = tool.execute(command="echo hello")

        assert result.success
        assert "tdd_nudge" not in result.content


if __name__ == "__main__":
    pytest.main([__file__])
