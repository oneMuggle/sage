"""Tests for backend.design.live_artifact (M5b)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.design.live_artifact import (
    LiveArtifactEngine,
    SourceBinding,
    _delete_binding,
    _load_binding,
    _save_binding,
    detect_kind,
    render_summary,
    validate_source_path,
)


class TestValidateSourcePath:
    def test_missing_file_raises_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            validate_source_path(str(tmp_path / "nope.xlsx"))

    def test_unsupported_extension_rejected(self, tmp_path: Path):
        path = tmp_path / "data.pdf"
        path.write_bytes(b"")
        with pytest.raises(ValueError, match="unsupported"):
            validate_source_path(str(path))

    def test_supported_extensions_pass(self, tmp_path: Path):
        for ext in (".xlsx", ".xls", ".csv", ".json"):
            path = tmp_path / f"data{ext}"
            path.write_text("{}" if ext == ".json" else "")
            validate_source_path(str(path))  # no raise


class TestDetectKind:
    def test_xlsx(self):
        assert detect_kind("/path/file.xlsx") == "xlsx"

    def test_xls(self):
        assert detect_kind("/path/file.xls") == "xlsx"

    def test_csv(self):
        assert detect_kind("/path/file.csv") == "csv"

    def test_json(self):
        assert detect_kind("/path/file.json") == "json"

    def test_unknown(self):
        assert detect_kind("/path/file.txt") == "unknown"


class TestSourceBindingPersistence:
    def test_round_trip(self, tmp_path: Path):
        binding = SourceBinding(
            kind="xlsx", file_path="/tmp/data.xlsx", name="data",
        )
        _save_binding(tmp_path, "proj-1", binding)
        loaded = _load_binding(tmp_path, "proj-1")
        assert loaded is not None
        assert loaded.kind == "xlsx"
        assert loaded.file_path == "/tmp/data.xlsx"
        assert loaded.name == "data"

    def test_delete_returns_true_when_present(self, tmp_path: Path):
        binding = SourceBinding(
            kind="json", file_path="/tmp/d.json", name="d",
        )
        _save_binding(tmp_path, "proj-2", binding)
        assert _delete_binding(tmp_path, "proj-2") is True
        assert _load_binding(tmp_path, "proj-2") is None

    def test_delete_returns_false_when_absent(self, tmp_path: Path):
        assert _delete_binding(tmp_path, "proj-missing") is False

    def test_malformed_binding_returns_none(self, tmp_path: Path):
        (tmp_path / "design" / "proj-bad").mkdir(parents=True)
        (tmp_path / "design" / "proj-bad" / "source.json").write_text(
            "not-json"
        )
        assert _load_binding(tmp_path, "proj-bad") is None


class TestBindAndUnbind:
    def test_bind_persists_binding(self, tmp_path: Path):
        path = tmp_path / "sales.xlsx"
        path.write_bytes(b"")
        engine = LiveArtifactEngine(tmp_path)
        binding = engine.bind("p1", str(path))
        assert binding.kind == "xlsx"
        assert binding.name == "sales"
        assert Path(binding.file_path).exists()
        assert engine.get_binding("p1") is not None

    def test_bind_explicit_kind_and_name(self, tmp_path: Path):
        path = tmp_path / "data.csv"
        path.write_text("a,b\n1,2\n")
        engine = LiveArtifactEngine(tmp_path)
        binding = engine.bind(
            "p2", str(path), kind="csv", name="custom",
        )
        assert binding.kind == "csv"
        assert binding.name == "custom"

    def test_bind_rejects_missing_file(self, tmp_path: Path):
        engine = LiveArtifactEngine(tmp_path)
        with pytest.raises(FileNotFoundError):
            engine.bind("p3", str(tmp_path / "missing.xlsx"))

    def test_unbind_removes_binding(self, tmp_path: Path):
        path = tmp_path / "f.json"
        path.write_text("{}")
        engine = LiveArtifactEngine(tmp_path)
        engine.bind("p4", str(path))
        assert engine.unbind("p4") is True
        assert engine.get_binding("p4") is None

    def test_unbind_returns_false_when_nothing(self, tmp_path: Path):
        engine = LiveArtifactEngine(tmp_path)
        assert engine.unbind("never-bound") is False


class TestRenderSummary:
    def test_json_summary_includes_content(self, tmp_path: Path):
        path = tmp_path / "data.json"
        path.write_text(json.dumps({"region": "华东", "sales": 42}))
        binding = SourceBinding(
            kind="json", file_path=str(path), name="data",
        )
        summary = render_summary(binding)
        assert "region" in summary
        assert "华东" in summary

    def test_json_summary_truncates_large_payload(self, tmp_path: Path):
        big = "x" * 8000
        path = tmp_path / "big.json"
        path.write_text(json.dumps({"payload": big}))
        binding = SourceBinding(
            kind="json", file_path=str(path), name="big",
        )
        summary = render_summary(binding)
        # After truncation the payload is no longer valid JSON so the
        # engine falls back to the raw truncated text.
        assert len(summary) < 8000 + 500
        assert summary.endswith("…")

    def test_csv_summary_uses_header_row(self, tmp_path: Path):
        path = tmp_path / "q.csv"
        path.write_text("quarter,revenue\nQ1,10\nQ2,20\nQ3,30\n")
        binding = SourceBinding(
            kind="csv", file_path=str(path), name="q",
        )
        summary = render_summary(binding)
        assert "quarter" in summary.lower() or "revenue" in summary.lower()
        assert "Q1" in summary or "10" in summary

    def test_xlsx_summary_renders_sheets(self, tmp_path: Path):
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = "销售"
        sheet.append(["季度", "金额"])
        sheet.append(["Q1", 100])
        sheet.append(["Q2", 200])
        path = tmp_path / "deck.xlsx"
        book.save(str(path))

        binding = SourceBinding(
            kind="xlsx", file_path=str(path), name="deck",
        )
        summary = render_summary(binding)
        assert "销售" in summary or "季度" in summary
        assert "Q1" in summary


class TestRefresh:
    @pytest.mark.asyncio()
    async def test_refresh_appends_source_summary_to_brief(self, tmp_path: Path):
        path = tmp_path / "d.json"
        path.write_text(json.dumps({"region": "华东"}))

        engine = LiveArtifactEngine(tmp_path)
        engine.bind("p1", str(path))

        class FakeProject:
            brief = "季度汇报"

        class FakeArtifact:
            id = "a1"
            version = 1

        class FakeStudio:
            def __init__(self) -> None:
                self.calls: list = []

            def get_project(self, pid: str) -> FakeProject:
                return FakeProject()

            async def generate(self, pid: str, brief: str = None):
                self.calls.append(brief)
                return FakeArtifact()

        studio = FakeStudio()
        result = await engine.refresh(studio, "p1")
        assert result.id == "a1"
        assert studio.calls, "studio.generate was not called"
        brief = studio.calls[0]
        assert "季度汇报" in brief
        assert "华东" in brief

    @pytest.mark.asyncio()
    async def test_refresh_falls_back_when_no_binding(self, tmp_path: Path):
        engine = LiveArtifactEngine(tmp_path)

        class FakeProject:
            brief = "plain brief"

        class FakeArtifact:
            id = "a2"
            version = 1

        class FakeStudio:
            def get_project(self, pid: str) -> FakeProject:
                return FakeProject()

            async def generate(self, pid: str, brief: str = None):
                return FakeArtifact()

        studio = FakeStudio()
        result = await engine.refresh(studio, "p1")
        assert result.id == "a2"
