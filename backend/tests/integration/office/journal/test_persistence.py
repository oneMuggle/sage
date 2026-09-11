"""journal persistence (workspace JSON + SQLite 元数据) 集成测试。

TDD: 先写失败测试，再实现 persistence.py + 修改 database.py。
"""
from pathlib import Path

import pytest

from backend.office.journal.errors import JournalSpecNotFoundError
from backend.office.journal.models import (
    CitationStyle,
    FontFamily,
    HeadingSpec,
    JournalGenerationRecord,
    JournalSpec,
)
from backend.office.journal.persistence import (
    ensure_journal_tables,
    list_generations,
    list_specs,
    load_spec,
    record_generation,
    save_spec,
)


def _sample_spec(spec_id="spec_abc123", filename="simple.docx") -> JournalSpec:
    return JournalSpec(
        spec_id=spec_id,
        template_sha256="deadbeef" * 8,
        template_filename=filename,
        font_body=FontFamily(
            family="宋体", ascii_family="Times New Roman", eastasia="宋体"
        ),
        font_heading=FontFamily(family="黑体", ascii_family="黑体", eastasia="黑体"),
        body_pt=12.0,
        heading_pt=16.0,
        line_spacing=1.5,
        margins_cm=2.54,
        headings=[HeadingSpec(keyword="摘要", level=1, expected_pt=16.0)],
        citation_style=CitationStyle.NUMERIC,
        page_size="A4",
    )


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    # 使用临时目录作为 workspace；SQLite 由 setup_test_db 注入临时 DB
    (tmp_path / "office" / "journal" / "specs").mkdir(parents=True)
    (tmp_path / "office" / "journal" / "cache").mkdir(parents=True)
    (tmp_path / "office" / "journal" / "generated").mkdir(parents=True)
    return tmp_path


def test_save_and_load_spec_round_trip(workspace):
    spec = _sample_spec()
    save_spec(workspace, spec)
    loaded = load_spec(workspace, spec.spec_id)
    assert loaded.spec_id == spec.spec_id
    assert loaded == spec


def test_list_specs_returns_sorted(workspace):
    s1 = _sample_spec(spec_id="spec_abc", filename="a.docx")
    s2 = _sample_spec(spec_id="spec_xyz", filename="b.docx")
    save_spec(workspace, s1)
    save_spec(workspace, s2)
    listed = list_specs(workspace)
    assert [s.spec_id for s in listed] == ["spec_abc", "spec_xyz"]


def test_load_spec_missing_raises(workspace):
    with pytest.raises(JournalSpecNotFoundError):
        load_spec(workspace, "spec_nonexistent")


def test_record_generation_round_trip(workspace):
    spec = _sample_spec()
    save_spec(workspace, spec)
    rec = JournalGenerationRecord(
        gen_id="gen_abc",
        spec_id=spec.spec_id,
        output_path=str(
            workspace / "office" / "journal" / "generated" / "paper.docx"
        ),
        mode="structured_fill",
        created_at=1736486400000,
        bytes_written=12345,
    )
    saved = record_generation(workspace, rec)
    assert saved == rec
    rows = list_generations(workspace, spec_id=spec.spec_id)
    assert len(rows) == 1
    assert rows[0].gen_id == "gen_abc"


def test_ensure_journal_tables_idempotent():
    ensure_journal_tables()
    ensure_journal_tables()  # 第二次不抛


def test_load_spec_path_traversal_raises(workspace):
    """C1: spec_id 含 .. 应被 is_within 拦截，不逃逸 workspace。"""
    with pytest.raises(JournalSpecNotFoundError):
        load_spec(workspace, "../../etc/passwd")


def test_save_spec_path_traversal_raises(workspace):
    """C1: save_spec 含 .. 的 spec_id 同样应被拦截。"""
    spec = _sample_spec(spec_id="../../etc/passwd")
    with pytest.raises(JournalSpecNotFoundError):
        save_spec(workspace, spec)


def test_load_spec_corrupt_json_raises_not_found(workspace):
    """M5: 损坏的 JSON 应包装为 JournalSpecNotFoundError，不泄露 Pydantic ValidationError。"""
    corrupt_path = (
        workspace / "office" / "journal" / "specs" / "spec_corrupt.json"
    )
    corrupt_path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(JournalSpecNotFoundError) as exc_info:
        load_spec(workspace, "spec_corrupt")
    assert "corrupt" in str(exc_info.value).lower()


def test_save_spec_atomic_cleanup_on_sqlite_failure(workspace, monkeypatch):
    """I2: SQLite 写入失败时，已写的 JSON 文件应被清理。"""
    spec = _sample_spec(spec_id="spec_atomic_test")
    # 让 SQLite INSERT 抛异常
    from backend.data.database import get_database

    real_get_connection = get_database().get_connection

    class _FailingConn:
        def execute(self, *args, **kwargs):
            raise RuntimeError("simulated SQLite failure")

        def __getattr__(self, name):
            return getattr(real_get_connection, name)

    monkeypatch.setattr(get_database(), "get_connection", lambda: _FailingConn())
    with pytest.raises(RuntimeError, match="simulated"):
        save_spec(workspace, spec)
    # JSON 文件应被清理
    json_path = workspace / "office" / "journal" / "specs" / "spec_atomic_test.json"
    assert not json_path.exists()
