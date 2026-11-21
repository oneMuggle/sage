"""文献调研最小闭环：模型 / 运行目录 / 门禁 / 导出 / 检索 / CLI。"""

from __future__ import annotations

import json

import pytest

from backend.literature.pipeline_models import (
    EvidenceRecord,
    GateReport,
    Outline,
    evidence_from_dict,
    outline_from_dict,
    paper_record_from_dict,
)

pytestmark = pytest.mark.unit


def _paper(key="p1", title="示例论文", authors=("张三",), year="2024"):
    return {
        "paper_key": key,
        "title": title,
        "authors": list(authors),
        "year": year,
        "venue": "示例期刊",
        "source_site": "demo",
    }


class TestPipelineModels:
    def test_paper_record_from_dict(self):
        record = paper_record_from_dict(_paper())
        assert record.paper_key == "p1"
        assert record.authors == ("张三",)
        with pytest.raises(ValueError, match="paper_key"):
            paper_record_from_dict({"title": "缺 key"})
        with pytest.raises(ValueError, match="title"):
            paper_record_from_dict({"paper_key": "p1", "title": " "})

    def test_evidence_from_dict_requires_paper_key(self):
        record = evidence_from_dict(
            {
                "evidence_id": "e1",
                "paper_key": "p1",
                "kind": "finding",
                "text": "发现 A",
                "locator": "p.3",
            }
        )
        assert record.kind == "finding"
        assert isinstance(record, EvidenceRecord)
        with pytest.raises(ValueError, match="paper_key"):
            evidence_from_dict({"evidence_id": "e1", "kind": "finding", "text": "x"})

    def test_outline_from_dict(self):
        outline = outline_from_dict(
            {
                "title": "综述",
                "sections": [
                    {"id": "s1", "title": "引言", "summary": "背景", "source_keys": ["p1"]}
                ],
            }
        )
        assert isinstance(outline, Outline)
        assert outline.sections[0].source_keys == ("p1",)
        with pytest.raises(ValueError, match="sections"):
            outline_from_dict({"title": "x", "sections": []})

    def test_outline_rejects_duplicate_section_ids(self):
        with pytest.raises(ValueError, match="重复"):
            outline_from_dict(
                {
                    "title": "x",
                    "sections": [
                        {"id": "s1", "title": "a"},
                        {"id": "s1", "title": "b"},
                    ],
                }
            )

    def test_gate_report_to_dict(self):
        report = GateReport(ok=False, errors=["bad"], warnings=["warn"], citations=["p1"])
        assert report.to_dict()["ok"] is False
        assert report.to_dict()["citations"] == ["p1"]


def test_paper_json_round_trip_uses_expected_fields():
    data = json.loads(json.dumps(_paper()))
    assert paper_record_from_dict(data).title == "示例论文"


class TestRunStore:
    def test_create_load_and_status(self, tmp_path):
        from backend.literature.run_store import create_run, load_run, run_status

        run = create_run(tmp_path, topic="大模型综述", site_id="xueshu789", run_id="r1")
        assert run.run_dir == tmp_path / "r1"
        assert (run.run_dir / "meta.json").is_file()
        loaded = load_run(run.run_dir)
        assert loaded.topic == "大模型综述"
        status = run_status(run)
        assert status["papers"] == 0
        assert status["has_draft"] is False

    def test_record_papers_dedupes_by_key(self, tmp_path):
        from backend.literature.run_store import create_run, read_jsonl, record_papers

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        added = record_papers(run, [_paper("p1"), _paper("p1"), _paper("p2")])
        assert added == 2
        assert len(read_jsonl(run.run_dir / "papers.jsonl")) == 2

    def test_record_evidence_rejects_unknown_paper(self, tmp_path):
        from backend.literature.run_store import create_run, record_evidence

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        with pytest.raises(ValueError, match="paper_key"):
            record_evidence(
                run,
                [
                    {
                        "evidence_id": "e1",
                        "paper_key": "missing",
                        "kind": "finding",
                        "text": "x",
                    }
                ],
            )

    def test_save_outline_and_draft(self, tmp_path):
        from backend.literature.run_store import (
            create_run,
            load_outline,
            read_draft,
            run_status,
            save_draft,
            save_outline,
        )

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        save_outline(run, {"title": "x", "sections": [{"id": "s1", "title": "引言"}]})
        assert load_outline(run).sections[0].id == "s1"
        save_draft(run, "# 草稿\n\n正文 [cite:p1]\n")
        assert "cite:p1" in read_draft(run)
        assert run_status(run)["has_draft"] is True

    def test_invalid_run_dir(self, tmp_path):
        from backend.literature.run_store import load_run

        with pytest.raises(ValueError, match="meta.json"):
            load_run(tmp_path / "missing")
