"""文献调研 claims / 元数据核验 / 证据支持测试。"""

from __future__ import annotations

import json

import pytest

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


class TestClaims:
    def test_extract_claims_from_paragraphs(self):
        from backend.literature.gates import extract_claims

        draft = (
            "# 综述\n\n"
            "背景段，无引用。\n\n"
            "方法段 [cite:p1]。\n\n"
            "对比段 [cite:p1, p2]。\n"
        )
        claims = extract_claims(draft)
        assert [c.claim_id for c in claims] == ["c0001", "c0002"]
        assert claims[0].citation_keys == ("p1",)
        assert claims[1].citation_keys == ("p1", "p2")
        assert "背景段" not in claims[0].text

    def test_verify_claims_classifies_supported_unresolved_unsupported(self):
        from backend.literature.gates import verify_claims
        from backend.literature.pipeline_models import Claim

        claims = [
            Claim("c1", "body", "有引用", ("p1",)),
            Claim("c2", "body", "未知引用", ("missing",)),
            Claim("c3", "body", "无引用", ()),
        ]
        result = verify_claims(claims, {"p1", "p2"})
        assert result[0].verdict == "supported"
        assert result[1].verdict == "unresolved"
        assert "missing" in result[1].notes
        assert result[2].verdict == "unsupported"

    def test_save_and_load_claims(self, tmp_path):
        from backend.literature.gates import verify_claims
        from backend.literature.pipeline_models import Claim
        from backend.literature.run_store import create_run, load_claims, save_claims

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        claims = verify_claims([Claim("c1", "body", "有引用", ("p1",))], {"p1"})
        save_claims(run, claims)
        loaded = load_claims(run)
        assert len(loaded) == 1
        assert loaded[0].verdict == "supported"
        assert loaded[0].citation_keys == ("p1",)

    def test_run_status_reports_claims(self, tmp_path):
        from backend.literature.pipeline_models import Claim
        from backend.literature.run_store import create_run, run_status, save_claims

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        save_claims(run, [Claim("c1", "body", "x", ("p1",))])
        status = run_status(run)
        assert status["claims"] == 1
        assert status["has_claims"] is True

    def test_cli_claims_flow(self, tmp_path):
        from backend.literature import cli

        root = tmp_path / "runs"
        cli.main(
            ["init", "--root", str(root), "--topic", "t", "--site", "demo", "--run-id", "r1"]
        )
        run_dir = root / "r1"
        papers = tmp_path / "papers.json"
        papers.write_text(json.dumps([_paper("p1")]), encoding="utf-8")
        cli.main(["record-papers", "--run", str(run_dir), "--json", str(papers)])
        draft = tmp_path / "draft.md"
        draft.write_text(
            "# 草稿\n\n正确引用 [cite:p1]。\n\n坏引用 [cite:missing]。\n",
            encoding="utf-8",
        )
        cli.main(["save-draft", "--run", str(run_dir), "--md", str(draft)])
        assert cli.main(["extract-claims", "--run", str(run_dir)]) == 0
        assert cli.main(["verify-claims", "--run", str(run_dir)]) == 1

        draft.write_text("# 草稿\n\n正确引用 [cite:p1]。\n", encoding="utf-8")
        cli.main(["save-draft", "--run", str(run_dir), "--md", str(draft)])
        assert cli.main(["verify-claims", "--run", str(run_dir)]) == 0


class _FakeLookup:
    def __init__(self, name, candidate):
        self.name = name
        self.candidate = candidate
        self.calls = 0

    def lookup(self, paper):
        self.calls += 1
        return self.candidate


class TestMetadataVerification:
    def _paper(self):
        from backend.literature.models import PaperRecord

        return PaperRecord(
            paper_key="doi:10.1/demo",
            title="示例论文",
            authors=("张三",),
            year="2024",
            venue="示例期刊",
            doi="10.1/demo",
        )

    def test_metadata_matches_title_year_author(self):
        from backend.literature.verify import metadata_matches

        paper = self._paper()
        assert metadata_matches(
            paper,
            {"title": "示例 论文", "year": "2024", "authors": ["张三"]},
        )
        assert not metadata_matches(
            paper,
            {"title": "别的论文", "year": "2024", "authors": ["张三"]},
        )
        assert not metadata_matches(
            paper,
            {"title": "示例论文", "year": "2023", "authors": ["张三"]},
        )
        assert not metadata_matches(
            paper,
            {"title": "示例论文", "year": "2024", "authors": ["李四"]},
        )

    def test_two_of_three_consensus(self):
        from backend.literature.verify import verify_paper_metadata

        paper = self._paper()
        good = {"title": "示例论文", "year": "2024", "authors": ["张三"]}
        bad = {"title": "其他", "year": "2024", "authors": ["张三"]}
        verdict = verify_paper_metadata(
            paper,
            [_FakeLookup("a", good), _FakeLookup("b", good), _FakeLookup("c", bad)],
        )
        assert verdict.status == "verified"
        assert verdict.matched == 2

        verdict = verify_paper_metadata(paper, [_FakeLookup("a", good)])
        assert verdict.status == "partial"

        verdict = verify_paper_metadata(paper, [_FakeLookup("a", bad)])
        assert verdict.status == "unverified"

    def test_no_external_id_is_skipped(self):
        from backend.literature.models import PaperRecord
        from backend.literature.verify import verify_paper_metadata

        paper = PaperRecord("cnki:demo", "示例论文", ("张三",), "2024")
        verdict = verify_paper_metadata(paper, [_FakeLookup("a", {})])
        assert verdict.status == "skipped"

    def test_verify_run_metadata_writes_report(self, tmp_path):
        from backend.literature.run_store import create_run, record_papers
        from backend.literature.verify import verify_run_metadata

        paper = {
            "paper_key": "doi:10.1/demo",
            "title": "示例论文",
            "authors": ["张三"],
            "year": "2024",
            "venue": "示例期刊",
            "doi": "10.1/demo",
        }
        run = create_run(tmp_path, "t", "demo", run_id="r1")
        record_papers(run, [paper])
        good = {"title": "示例论文", "year": "2024", "authors": ["张三"]}
        report = verify_run_metadata(
            run, [_FakeLookup("a", good), _FakeLookup("b", good)]
        )
        assert report["verified"] == 1
        assert (run.run_dir / "metadata_verification.json").is_file()


class TestEvidenceSupport:
    def test_claim_without_evidence_is_flagged(self):
        from backend.literature.pipeline_models import Claim
        from backend.literature.verify import apply_evidence_support

        claims = [Claim("c1", "body", "x", ("p1",), verdict="supported")]
        result = apply_evidence_support(claims, [])
        assert result[0].verdict == "flagged"
        assert "证据" in result[0].notes

    def test_claim_with_evidence_stays_supported(self):
        from backend.literature.pipeline_models import Claim, EvidenceRecord
        from backend.literature.verify import apply_evidence_support

        claims = [Claim("c1", "body", "x", ("p1",), verdict="supported")]
        evidence = [EvidenceRecord("e1", "p1", "finding", "发现")]
        result = apply_evidence_support(claims, evidence)
        assert result[0].verdict == "supported"

    def test_unresolved_claim_is_unchanged(self):
        from backend.literature.pipeline_models import Claim
        from backend.literature.verify import apply_evidence_support

        claims = [Claim("c1", "body", "x", ("missing",), verdict="unresolved")]
        result = apply_evidence_support(claims, [])
        assert result[0].verdict == "unresolved"

    def test_cli_verify_metadata(self, tmp_path, monkeypatch):
        from backend.literature import cli

        root = tmp_path / "runs"
        cli.main(
            ["init", "--root", str(root), "--topic", "t", "--site", "demo", "--run-id", "r1"]
        )
        run_dir = root / "r1"
        papers = tmp_path / "papers.json"
        papers.write_text(
            json.dumps(
                [
                    {
                        "paper_key": "doi:10.1/demo",
                        "title": "示例论文",
                        "authors": ["张三"],
                        "year": "2024",
                        "doi": "10.1/demo",
                    }
                ]
            ),
            encoding="utf-8",
        )
        cli.main(["record-papers", "--run", str(run_dir), "--json", str(papers)])
        good = {"title": "示例论文", "year": "2024", "authors": ["张三"]}
        monkeypatch.setattr(
            cli,
            "default_lookups",
            lambda: [_FakeLookup("a", good), _FakeLookup("b", good)],
        )
        assert cli.main(["verify-metadata", "--run", str(run_dir)]) == 0
        assert (run_dir / "metadata_verification.json").is_file()
