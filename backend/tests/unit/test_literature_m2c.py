"""M2c：语义 claim support / EvidenceLedger / 四态报告测试。"""

from __future__ import annotations

import json

import pytest

from backend.literature.pipeline_models import Claim

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


class TestClaimSupport:
    def test_apply_supported_and_joint_notes(self):
        from backend.literature.support import apply_claim_support

        claims = [Claim("c1", "body", "x", ("p1",), verdict="flagged", notes="旧备注")]
        result = apply_claim_support(
            claims,
            [
                {
                    "claim_id": "c1",
                    "support": "supported",
                    "rationale": "证据 e1 直接支持",
                    "evidence_refs": ["e1"],
                }
            ],
        )
        assert result[0].verdict == "supported"
        assert "旧备注" in result[0].notes
        assert "证据 e1 直接支持" in result[0].notes
        assert "e1" in result[0].notes

    def test_unresolved_claim_is_not_overwritten(self):
        from backend.literature.support import apply_claim_support

        claims = [Claim("c1", "body", "x", ("missing",), verdict="unresolved")]
        result = apply_claim_support(
            claims, [{"claim_id": "c1", "support": "supported"}]
        )
        assert result[0].verdict == "unresolved"

    def test_invalid_support_raises(self):
        from backend.literature.support import apply_claim_support

        claims = [Claim("c1", "body", "x", ("p1",))]
        with pytest.raises(ValueError, match="support"):
            apply_claim_support(claims, [{"claim_id": "c1", "support": "maybe"}])

    def test_unknown_claim_id_raises(self):
        from backend.literature.support import apply_claim_support

        claims = [Claim("c1", "body", "x", ("p1",))]
        with pytest.raises(ValueError, match="未知"):
            apply_claim_support(claims, [{"claim_id": "c9", "support": "supported"}])

    def test_all_four_support_states(self):
        from backend.literature.support import apply_claim_support

        claims = [Claim(f"c{i}", "body", "x", ("p1",)) for i in range(1, 5)]
        states = ["supported", "flagged", "unsupported", "unclear"]
        result = apply_claim_support(
            claims,
            [
                {"claim_id": f"c{i + 1}", "support": state}
                for i, state in enumerate(states)
            ],
        )
        assert [c.verdict for c in result] == states


class TestLedger:
    def _run(self, tmp_path):
        from backend.literature.gates import extract_claims, verify_claims
        from backend.literature.run_store import (
            create_run,
            record_evidence,
            record_papers,
            record_query,
            save_claims,
            save_draft,
        )

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        record_query(run, "q", "demo", 2)
        record_papers(run, [_paper("p1"), _paper("p2")])
        record_evidence(
            run,
            [
                {
                    "evidence_id": "e1",
                    "paper_key": "p1",
                    "kind": "finding",
                    "text": "发现",
                    "locator": "p.3",
                }
            ],
        )
        draft = "# 草稿\n\n引用 [cite:p1] 和 [cite:p2]。\n"
        save_draft(run, draft)
        save_claims(run, verify_claims(extract_claims(draft), {"p1", "p2"}))
        return run

    def test_build_ledger_merges_evidence_and_claims(self, tmp_path):
        from backend.literature.ledger import build_ledger, ledger_stats

        run = self._run(tmp_path)
        ledger = build_ledger(run)
        assert len(ledger.entries) == 3  # 1 evidence + 2 claim citation
        assert ledger_stats(ledger) == {"evidence": 1, "claim": 2}
        assert (run.run_dir / "ledger.json").is_file()

    def test_external_entries_and_dedupe(self, tmp_path):
        from backend.literature.ledger import build_ledger
        from backend.literature.run_store import (
            create_run,
            record_papers,
            save_claims,
        )

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        record_papers(run, [_paper("p1")])
        save_claims(run, [Claim("c1", "body", "x", ("p1",))])
        external = [
            {
                "paper_key": "p1",
                "source_type": "wiki",
                "source_id": "S1",
                "locator": "sec 2",
            },
            {
                "paper_key": "p1",
                "source_type": "wiki",
                "source_id": "S1",
                "locator": "sec 2",
            },
        ]
        ledger = build_ledger(run, external)
        assert len(ledger.entries) == 2  # 1 claim + 1 deduped external

    def test_load_ledger_roundtrip(self, tmp_path):
        from backend.literature.ledger import build_ledger, load_ledger

        run = self._run(tmp_path)
        built = build_ledger(run)
        loaded = load_ledger(run)
        assert len(loaded.entries) == len(built.entries)


class TestReport:
    def test_report_groups_four_states_and_writes_files(self, tmp_path):
        from backend.literature.ledger import build_ledger
        from backend.literature.report import build_verification_report
        from backend.literature.run_store import (
            create_run,
            record_papers,
            save_claims,
            write_json,
        )

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        record_papers(run, [_paper("p1"), _paper("p2")])
        save_claims(
            run,
            [
                Claim("c1", "body", "支持", ("p1",), verdict="supported"),
                Claim("c2", "body", "待复核", ("p1",), verdict="flagged"),
                Claim("c3", "body", "不支持", ("p2",), verdict="unsupported"),
                Claim("c4", "body", "不清楚", ("p1",), verdict="unclear"),
            ],
        )
        write_json(
            run.run_dir / "metadata_verification.json",
            {"verified": 1, "partial": 0, "unverified": 1, "skipped": 0, "items": []},
        )
        build_ledger(run)
        report = build_verification_report(run)
        assert report["summary"]["supported"] == 1
        assert report["summary"]["flagged"] == 1
        assert report["summary"]["unsupported"] == 1
        assert report["summary"]["unclear"] == 1
        assert (run.run_dir / "export" / "verification_report.md").is_file()
        assert (run.run_dir / "export" / "verification_report.json").is_file()
        md = (run.run_dir / "export" / "verification_report.md").read_text(
            encoding="utf-8"
        )
        assert "supported (1)" in md
        assert "unclear (1)" in md


class TestM2cCli:
    def test_apply_support_ledger_and_report(self, tmp_path):
        from backend.literature import cli
        from backend.literature.run_store import (
            create_run,
            load_claims,
            load_run,
            record_papers,
            save_claims,
        )

        root = tmp_path / "runs"
        cli.main(
            ["init", "--root", str(root), "--topic", "t", "--site", "demo", "--run-id", "r1"]
        )
        run_dir = root / "r1"
        run = load_run(run_dir) if (run_dir / "meta.json").is_file() else create_run(
            root, "t", "demo", run_id="r1"
        )
        record_papers(run, [_paper("p1")])
        save_claims(run, [Claim("c1", "body", "x", ("p1",))])
        judgments = tmp_path / "judgments.json"
        judgments.write_text(
            json.dumps(
                [{"claim_id": "c1", "support": "supported", "rationale": "ok"}]
            ),
            encoding="utf-8",
        )
        assert cli.main(
            ["apply-claim-support", "--run", str(run_dir), "--json", str(judgments)]
        ) == 0
        assert load_claims(load_run(run_dir))[0].verdict == "supported"
        assert cli.main(["build-ledger", "--run", str(run_dir)]) == 0
        assert (run_dir / "ledger.json").is_file()
        assert cli.main(["report", "--run", str(run_dir)]) == 0
        assert (run_dir / "export" / "verification_report.md").is_file()
