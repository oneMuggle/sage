"""把通过门禁的运行导出为 Markdown / BibTeX / paper-writing 交接数据。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence

from .gates import build_references, run_gates
from .models import PaperRecord
from .run_store import (
    LiteratureRun,
    atomic_write_text,
    list_papers,
    read_draft,
    write_json,
)


def _bibtex_entry(paper: PaperRecord) -> str:
    authors = " and ".join(paper.authors) if paper.authors else "佚名"
    fields = [
        f"  title = {{{paper.title}}}",
        f"  author = {{{authors}}}",
        f"  year = {{{paper.year or ''}}}",
    ]
    if paper.venue:
        fields.append(f"  journal = {{{paper.venue}}}")
    if paper.doi:
        fields.append(f"  doi = {{{paper.doi}}}")
    return "@article{" + paper.paper_key + ",\n" + ",\n".join(fields) + "\n}\n"


def build_bibtex(papers: Sequence[PaperRecord], cited_keys: Sequence[str]) -> str:
    by_key = {p.paper_key: p for p in papers}
    return "\n".join(_bibtex_entry(by_key[key]) for key in cited_keys if key in by_key)


def build_handoff(run: LiteratureRun) -> Dict[str, Any]:
    papers = list_papers(run)
    draft = read_draft(run)
    _, entries = build_references(draft, papers)
    references = []
    for entry in entries:
        paper = entry["paper"]
        references.append(
            {
                "key": entry["key"],
                "ref_type": "journal",
                "title": paper["title"],
                "authors": paper["authors"],
                "year": paper["year"] or "",
                "source": paper["venue"] or "",
                "doi": paper["doi"] or "",
            }
        )
    return {"references": references, "draft_path": str(run.run_dir / "draft.md")}


def export_run(run: LiteratureRun) -> Dict[str, Path]:
    report = run_gates(run)
    if not report.ok:
        raise ValueError("门禁未通过，无法导出: " + "; ".join(report.errors))

    papers = list_papers(run)
    draft = read_draft(run)
    references_md, entries = build_references(draft, papers)
    export_dir = run.run_dir / "export"
    final = draft.rstrip() + "\n\n## 参考文献\n\n" + references_md + "\n"
    final_path = export_dir / "final.md"
    refs_path = export_dir / "references.json"
    bib_path = export_dir / "papers.bib"
    atomic_write_text(final_path, final)
    write_json(refs_path, {"style": "gbt7714", "entries": entries})
    atomic_write_text(bib_path, build_bibtex(papers, report.citations))
    return {"final": final_path, "references": refs_path, "bibtex": bib_path}
