"""M2c 收尾：Rubric 评审与 IEEE 引用样式测试。"""

from __future__ import annotations

import json

import pytest

from backend.literature.models import PaperRecord

pytestmark = pytest.mark.unit


def _paper(key, title=None, authors=("张三",), year="2024", site="demo"):
    return PaperRecord(
        paper_key=key,
        title=title or f"示例论文 {key}",
        authors=tuple(authors),
        year=year,
        venue="示例期刊",
        source_site=site,
    )


def _rich_run(tmp_path):
    """构造一个四维都能拿满分的合成运行（15 篇文献、3 次检索、全有证据）。"""
    from backend.literature.gates import extract_claims, run_gates, verify_claims
    from backend.literature.run_store import (
        create_run,
        record_evidence,
        record_papers,
        record_query,
        save_claims,
        save_draft,
        save_outline,
        write_json,
    )

    run = create_run(tmp_path, "综述主题", "demo", run_id="r1")
    for index in range(3):
        record_query(run, f"查询 {index + 1}", "demo", 10)
    record_papers(
        run,
        [
            {
                "paper_key": f"p{index}",
                "title": f"示例论文 {index}",
                "authors": ["张三"],
                "year": "2024",
                "venue": "示例期刊",
                "source_site": f"site{index % 3}",
            }
            for index in range(15)
        ],
    )
    record_evidence(
        run,
        [
            {
                "evidence_id": f"e{index}",
                "paper_key": f"p{index}",
                "kind": "finding",
                "text": f"发现 {index}",
                "locator": f"p.{index + 1}",
            }
            for index in range(15)
        ],
    )
    save_outline(
        run,
        {
            "title": "综述",
            "sections": [
                {"id": "s1", "title": "引言", "source_keys": ["p0"]},
                {"id": "s2", "title": "方法", "source_keys": ["p1"]},
            ],
        },
    )
    draft = (
        "## 引言\n\n"
        + "研究背景说明。" * 250
        + " [cite:p0] [cite:p1] [cite:p2] [cite:p3] [cite:p4] [cite:p5]\n\n"
        + "## 方法\n\n"
        + "方法描述内容。" * 250
        + " [cite:p6] [cite:p7] [cite:p8] [cite:p9] [cite:p10] [cite:p11]"
        + " [cite:p12] [cite:p13] [cite:p14]\n"
    )
    save_draft(run, draft)
    assert run_gates(run).ok
    write_json(
        run.run_dir / "metadata_verification.json",
        {"verified": 15, "partial": 0, "unverified": 0, "skipped": 0},
    )
    paper_keys = {f"p{index}" for index in range(15)}
    save_claims(run, verify_claims(extract_claims(draft), paper_keys))
    return run, draft


class TestRubricReview:
    def test_rich_run_scores_full_marks(self, tmp_path):
        from backend.literature.rubric import DISCLAIMER, review_run

        run, _ = _rich_run(tmp_path)
        review = review_run(run)
        assert review["total_score"] == 20
        assert review["max_score"] == 20
        assert review["band"] == "优"
        assert review["disclaimer"] == DISCLAIMER
        assert [dimension["score"] for dimension in review["dimensions"]] == [5, 5, 5, 5]
        assert [dimension["id"] for dimension in review["dimensions"]] == [
            "method",
            "coverage",
            "logic",
            "writing",
        ]

    def test_empty_run_scores_zero_and_lists_issues(self, tmp_path):
        from backend.literature.rubric import review_run
        from backend.literature.run_store import create_run

        run = create_run(tmp_path, "空运行", "demo", run_id="r1")
        review = review_run(run)
        assert review["total_score"] == 0
        assert review["band"] == "待改进"
        issues = {
            issue
            for dimension in review["dimensions"]
            for issue in dimension["issues"]
        }
        assert "检索日志为空" in issues
        assert "缺少大纲 outline.json" in issues
        assert "claims 账本为空（先运行 verify-claims）" in issues
        assert "门禁未通过（引用/参考文献不完整）" in issues

    def test_writes_markdown_and_status_flag(self, tmp_path):
        from backend.literature.rubric import DISCLAIMER, review_run
        from backend.literature.run_store import run_status

        run, _ = _rich_run(tmp_path)
        review = review_run(run)
        md_path = run.run_dir / "export" / "rubric_review.md"
        json_path = run.run_dir / "export" / "rubric_review.json"
        assert md_path.is_file()
        assert json_path.is_file()
        assert review["paths"]["markdown"] == str(md_path)
        markdown = md_path.read_text(encoding="utf-8")
        assert "总分：20/20（优）" in markdown
        assert DISCLAIMER in markdown
        assert run_status(run)["has_rubric_review"] is True

    def test_partial_coverage_flags_issues(self, tmp_path):
        from backend.literature.gates import extract_claims, verify_claims
        from backend.literature.rubric import review_run
        from backend.literature.run_store import (
            create_run,
            record_papers,
            record_query,
            save_claims,
            save_draft,
        )

        run = create_run(tmp_path, "部分覆盖", "demo", run_id="r1")
        record_query(run, "唯一查询", "demo", 3)
        record_papers(
            run,
            [
                {"paper_key": "p1", "title": "论文一", "authors": ["张三"]},
                {"paper_key": "p2", "title": "论文二", "authors": ["李四"]},
            ],
        )
        draft = "只有一段带引用 [cite:p1] 的文字。"
        save_draft(run, draft)
        save_claims(run, verify_claims(extract_claims(draft), {"p1", "p2"}))
        review = review_run(run)
        method, coverage = review["dimensions"][0], review["dimensions"][1]
        assert any("检索次数偏少" in issue for issue in method["issues"])
        assert any("文献量过少" in issue for issue in coverage["issues"])
        assert any("部分文献未被引用" in issue for issue in coverage["issues"])


class TestIeeeStyle:
    def test_ieee_authors_and_ordering(self):
        from backend.literature.gates import build_references

        papers = [
            _paper(
                "p1",
                title="Attention Is All You Need",
                authors=("John Smith", "Jane Doe", "X Y"),
            ),
            _paper("p2", title="中文论文", authors=("张三",)),
            _paper("p3", title="Many Authors", authors=("A B", "C D", "E F", "G H")),
        ]
        text, entries = build_references(
            "[cite:p1][cite:p2][cite:p3]", papers, style="ieee"
        )
        lines = text.splitlines()
        assert lines[0].startswith(
            '[1] J. Smith, J. Doe, and X. Y, "Attention Is All You Need,"'
        )
        assert lines[1].startswith("[2] 张三,")
        assert "et al." in lines[2]
        assert [entry["key"] for entry in entries] == ["p1", "p2", "p3"]

    def test_ieee_export_records_style(self, tmp_path):
        from backend.literature.export import export_run

        run, _ = _rich_run(tmp_path)
        paths = export_run(run, style="ieee")
        data = json.loads(paths["references"].read_text(encoding="utf-8"))
        assert data["style"] == "ieee"
        final = paths["final"].read_text(encoding="utf-8")
        assert '"示例论文 0,"' in final

    def test_unsupported_style_raises(self):
        from backend.literature.gates import build_references

        with pytest.raises(ValueError, match="暂不支持的引用样式"):
            build_references("[cite:p1]", [_paper("p1")], style="apa")

    def test_cli_rubric_and_export_style(self, tmp_path):
        from backend.literature import cli

        run, _ = _rich_run(tmp_path)
        assert cli.main(["rubric", "--run", str(run.run_dir)]) == 0
        assert (run.run_dir / "export" / "rubric_review.json").is_file()
        assert cli.main(["export", "--run", str(run.run_dir), "--style", "ieee"]) == 0
        data = json.loads(
            (run.run_dir / "export" / "references.json").read_text(encoding="utf-8")
        )
        assert data["style"] == "ieee"
