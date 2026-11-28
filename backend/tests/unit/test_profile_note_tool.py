"""profile_record_note 工具（spec §7.1）。"""

from pathlib import Path

import pytest

from backend.literature.knowledge import read_sidecar, sidecar_path
from backend.tools.profile_note_tool import ProfileRecordNoteTool

pytestmark = pytest.mark.unit


def test_record_note_writes_sidecar(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    tool = ProfileRecordNoteTool()
    result = tool.execute(
        site_id="demo",
        note_id="download-ddata-missing",
        title="结果行 href 必须取元素属性",
        symptom="下载报参数错误",
        cause="快照 URL 被截断",
        workaround="用 browser_interact action=attr 读 href",
        severity="blocker",
        applies_to=["pdf.entry"],
        source_run="run-001",
    )
    assert result.success is True, result.error
    payload = read_sidecar(sidecar_path(tmp_path, "demo", "notes"))
    notes = payload["notes"]
    assert len(notes) == 1
    assert notes[0]["id"] == "download-ddata-missing"
    assert notes[0]["severity"] == "blocker"


def test_record_note_with_same_id_overwrites(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    tool = ProfileRecordNoteTool()
    tool.execute(
        site_id="demo",
        note_id="dup",
        title="第一版",
        symptom="s",
        workaround="w",
        severity="degraded",
    )
    result = tool.execute(
        site_id="demo",
        note_id="dup",
        title="第二版",
        symptom="s2",
        workaround="w2",
        severity="blocker",
    )
    assert result.success is True, result.error
    payload = read_sidecar(sidecar_path(tmp_path, "demo", "notes"))
    notes = payload["notes"]
    assert len(notes) == 1
    assert notes[0]["title"] == "第二版"


def test_invalid_severity_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    tool = ProfileRecordNoteTool()
    result = tool.execute(
        site_id="demo",
        note_id="x",
        title="t",
        symptom="s",
        workaround="w",
        severity="catastrophic",
    )
    assert result.success is False


def test_invalid_note_id_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    tool = ProfileRecordNoteTool()
    result = tool.execute(
        site_id="demo",
        note_id="Bad Id",
        title="t",
        symptom="s",
        workaround="w",
        severity="blocker",
    )
    assert result.success is False


def test_main_profile_yaml_is_untouched(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    main = tmp_path / "demo.yaml"
    main.write_text("id: demo\n", encoding="utf-8")
    tool = ProfileRecordNoteTool()
    tool.execute(
        site_id="demo",
        note_id="x",
        title="t",
        symptom="s",
        workaround="w",
        severity="blocker",
    )
    assert main.read_text(encoding="utf-8") == "id: demo\n"
