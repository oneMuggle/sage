"""写后语法诊断单元测试（G8）：write/edit/apply_patch 的 diagnostics 附加。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.edit_tool import EditTool
from backend.tools.file_tool import WriteFileTool
from backend.tools.patch_tool import ApplyPatchTool
from backend.tools.write_diagnostics import _syntax_check, attach_diagnostics

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    d = tmp_path / "ws"
    d.mkdir()
    return d


def _tool(cls, root):
    return cls(policy=ToolPolicy(workspace_root=str(root)))


# ---------------------------------------------------------------------------
# 单元：_syntax_check / attach_diagnostics
# ---------------------------------------------------------------------------


def test_syntax_check_reports_error_with_line(ws):
    bad = ws / "bad.py"
    bad.write_text("def f(:\n    pass\n", encoding="utf-8")
    issue = _syntax_check(bad)
    assert issue is not None
    assert issue["severity"] == "error"
    assert issue["line"] == 1


def test_syntax_check_clean_and_non_python(ws):
    good = ws / "good.py"
    good.write_text("x = 1\n", encoding="utf-8")
    assert _syntax_check(good) is None

    text = ws / "note.md"
    text.write_text("def f(:\n", encoding="utf-8")
    assert _syntax_check(text) is None  # 非 .py 不诊断


def test_attach_diagnostics_appends_note(ws):
    bad = ws / "bad.py"
    bad.write_text("def f(:\n", encoding="utf-8")
    content = {"path": str(bad)}
    attached = attach_diagnostics(content, str(bad))
    assert attached is content
    assert attached["diagnostics"][0]["severity"] == "error"
    assert "语法问题" in attached["diagnostics_note"]


def test_attach_diagnostics_never_raises(ws, monkeypatch):
    good = ws / "ok.py"
    good.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "backend.tools.write_diagnostics._syntax_check",
        lambda p: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    content = {"path": str(good)}
    assert attach_diagnostics(content, str(good)) is content
    assert "diagnostics" not in content


# ---------------------------------------------------------------------------
# 集成：三个写入工具的成功结果携带诊断
# ---------------------------------------------------------------------------


def test_write_file_reports_syntax_error(ws):
    result = _tool(WriteFileTool, ws).execute(
        path=str(ws / "broken.py"), content="def f(:\n"
    )
    assert result.success is True  # 写入本身成功
    assert result.content["diagnostics"][0]["line"] == 1
    assert "语法问题" in result.content["diagnostics_note"]


def test_write_file_clean_python_has_no_diagnostics(ws):
    result = _tool(WriteFileTool, ws).execute(path=str(ws / "fine.py"), content="x = 1\n")
    assert result.success is True
    assert "diagnostics" not in result.content


def test_edit_file_reports_syntax_error_after_edit(ws):
    (ws / "app.py").write_text("value = 1\n", encoding="utf-8")
    result = _tool(EditTool, ws).execute(
        file_path=str(ws / "app.py"),
        old_string="value = 1",
        new_string="def broken(:\n",
    )
    assert result.success is True
    assert result.content["diagnostics"][0]["severity"] == "error"


def test_apply_patch_collects_per_file_diagnostics(ws):
    (ws / "a.py").write_text("ok = 1\n", encoding="utf-8")
    result = _tool(ApplyPatchTool, ws).execute(
        patches=[
            {
                "file_path": str(ws / "a.py"),
                "old_string": "ok = 1",
                "new_string": "def f(:\n",
            },
            {
                "file_path": str(ws / "b.py"),
                "old_string": "keep",
                "new_string": "also",
            },
        ]
    )
    assert result.success is False  # b.py 不存在 → 整批拒绝（原子性优先）


def test_apply_patch_diagnostics_on_success(ws):
    (ws / "a.py").write_text("ok = 1\n", encoding="utf-8")
    (ws / "b.py").write_text("fine = 2\n", encoding="utf-8")
    result = _tool(ApplyPatchTool, ws).execute(
        patches=[
            {
                "file_path": str(ws / "a.py"),
                "old_string": "ok = 1",
                "new_string": "def f(:\n",
            },
            {
                "file_path": str(ws / "b.py"),
                "old_string": "fine = 2",
                "new_string": "fine = 3",
            },
        ]
    )
    assert result.success is True
    assert len(result.content["diagnostics"]) == 1
    assert result.content["diagnostics"][0]["path"].endswith("a.py")
