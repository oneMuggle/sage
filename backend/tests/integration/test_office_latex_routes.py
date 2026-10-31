"""Integration tests for the read-only LaTeX preview endpoint."""

from __future__ import annotations

import zipfile
from pathlib import Path

import httpx
import pymupdf
import pytest
import pytest_asyncio

from backend.data import database as database_module
from backend.data.database import Database
from backend.main import app


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest_asyncio.fixture()
async def client(db: Database):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


def _write(workspace: Path, name: str, text: str) -> Path:
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.asyncio()
async def test_read_latex_returns_structured_blocks(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    main = _write(
        workspace,
        "paper/main.tex",
        r"""
\documentclass{article}
\title{Demo Paper}
\author{Alice}
\begin{document}
\section{Introduction}
See $E=mc^2$ and \cite{knuth84}.
\[
a^2+b^2=c^2
\]
\end{document}
""",
    )

    resp = await client.post(
        "/api/v1/office/latex/read",
        json={"workspace_path": str(workspace), "file_path": str(main)},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["kind"] == "latex"
    assert payload["structured"]["metadata"]["title"] == "Demo Paper"
    types = [block["type"] for block in payload["structured"]["blocks"]]
    assert "heading" in types
    assert "equation" in types
    assert "\\documentclass" in payload["content"]


@pytest.mark.asyncio()
async def test_read_latex_rejects_path_outside_workspace(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.tex"
    outside.write_text("\\documentclass{article}", encoding="utf-8")

    resp = await client.post(
        "/api/v1/office/latex/read",
        json={"workspace_path": str(workspace), "file_path": str(outside)},
    )

    assert resp.status_code == 400


@pytest.mark.asyncio()
async def test_read_latex_missing_file_returns_404(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    resp = await client.post(
        "/api/v1/office/latex/read",
        json={
            "workspace_path": str(workspace),
            "file_path": str(workspace / "missing.tex"),
        },
    )

    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_read_latex_rejects_extra_fields(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    main = _write(workspace, "a.tex", "\\documentclass{article}")

    resp = await client.post(
        "/api/v1/office/latex/read",
        json={
            "workspace_path": str(workspace),
            "file_path": str(main),
            "unexpected": True,
        },
    )

    assert resp.status_code == 422


_TEMPLATE = r"""
\documentclass{article}
\title{Old Title}
\author{Old Author}
\begin{document}
\begin{abstract}
Old abstract.
\end{abstract}
<<note>>
\end{document}
"""


@pytest.mark.asyncio()
async def test_template_analyze_and_fill(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template = _write(workspace, "paper.tex", _TEMPLATE)

    analyzed = await client.post(
        "/api/v1/office/latex/template/analyze",
        json={"workspace_path": str(workspace), "file_path": str(template)},
    )
    assert analyzed.status_code == 200
    profile = analyzed.json()
    assert profile["kind"] == "latex-template"
    slot_names = {slot["name"] for slot in profile["slots"]}
    assert {"title", "author", "abstract"}.issubset(slot_names)
    placeholder = next(
        slot["name"] for slot in profile["slots"] if slot["kind"] == "placeholder"
    )

    filled = await client.post(
        "/api/v1/office/latex/template/fill",
        json={
            "workspace_path": str(workspace),
            "template_path": str(template),
            "output_filename": "paper-filled.tex",
            "data": {
                "title": "New & Title",
                "author": ["Alice", "Bob"],
                "abstract": "New abstract.",
                placeholder: "Thanks",
            },
        },
    )
    assert filled.status_code == 200
    result = filled.json()
    assert result["ok"] is True
    assert result["filled_count"] == 4
    output = workspace / "paper-filled.tex"
    assert output.is_file()
    assert r"New \& Title" in output.read_text(encoding="utf-8")


@pytest.mark.asyncio()
async def test_template_fill_missing_required_returns_422(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template = _write(workspace, "paper.tex", _TEMPLATE)

    resp = await client.post(
        "/api/v1/office/latex/template/fill",
        json={
            "workspace_path": str(workspace),
            "template_path": str(template),
            "output_filename": "out.tex",
            "data": {"title": "Only title"},
        },
    )

    assert resp.status_code == 422


@pytest.mark.asyncio()
async def test_audit_latex_returns_anchored_issues(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    main = _write(
        workspace,
        "paper.tex",
        r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\section{Introduction}
\cite{missing}
\begin{thebibliography}{9}
\bibitem{known} Known.
\end{thebibliography}
\write18{echo unsafe}
\end{document}
""",
    )

    resp = await client.post(
        "/api/v1/office/latex/audit",
        json={
            "workspace_path": str(workspace),
            "file_path": str(main),
            "required_sections": ["Introduction", "Conclusion"],
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    rules = {issue["rule_id"] for issue in payload["issues"]}
    assert "LATEX-CITE-UNDEFINED" in rules
    assert "LATEX-UNSAFE-COMMAND" in rules
    assert "LATEX-SECTION-REQUIRED" in rules
    assert any(issue.get("anchor") for issue in payload["issues"])


@pytest.mark.asyncio()
async def test_compile_without_engine_degrades(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    main = _write(
        workspace,
        "paper.tex",
        r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
Hello.
\end{document}
""",
    )
    monkeypatch.setattr(
        "backend.office.latex.compile.shutil.which", lambda name: None
    )

    resp = await client.post(
        "/api/v1/office/latex/compile",
        json={
            "workspace_path": str(workspace),
            "file_path": str(main),
            "output_filename": "out.pdf",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert resp.json()["code"] == "no_engine"


@pytest.mark.asyncio()
async def test_latexdiff_without_tool_degrades(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = _write(workspace, "v1.tex", "\\documentclass{article}")
    revised = _write(workspace, "v2.tex", "\\documentclass{article}")
    monkeypatch.setattr(
        "backend.office.latex.diff.shutil.which", lambda name: None
    )

    resp = await client.post(
        "/api/v1/office/latex/diff",
        json={
            "workspace_path": str(workspace),
            "original_path": str(original),
            "revised_path": str(revised),
            "output_filename": "diff.tex",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert resp.json()["code"] == "no_latexdiff"


def _write_project_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("paper/main.tex", "\\documentclass{article}")
        archive.writestr("paper/sections/intro.tex", "\\section{Intro}")
        archive.writestr("paper/figs/arch.png", b"png")
    return path


@pytest.mark.asyncio()
async def test_extract_latex_project_zip(client: httpx.AsyncClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive = _write_project_zip(workspace / "project.zip")

    resp = await client.post(
        "/api/v1/office/latex/project/extract",
        json={
            "workspace_path": str(workspace),
            "zip_path": str(archive),
            "output_dir_name": "imported",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["project_dir"] == "imported"
    assert payload["main_file"] == "imported/paper/main.tex"
    assert payload["files_count"] == 3
    assert (workspace / "imported" / "paper" / "main.tex").is_file()


@pytest.mark.asyncio()
async def test_extract_latex_project_refuses_existing_dir(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "imported").mkdir()
    archive = _write_project_zip(workspace / "project.zip")

    resp = await client.post(
        "/api/v1/office/latex/project/extract",
        json={
            "workspace_path": str(workspace),
            "zip_path": str(archive),
            "output_dir_name": "imported",
        },
    )

    assert resp.status_code == 422


def _write_pdf(path: Path, *, pages: int = 1) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595.28, height=841.89)
        page.insert_text((72, 100), "Hello")
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.asyncio()
async def test_audit_latex_pdf_returns_issues(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pdf = _write_pdf(workspace / "main.pdf", pages=2)

    resp = await client.post(
        "/api/v1/office/latex/pdf/audit",
        json={
            "workspace_path": str(workspace),
            "file_path": str(pdf),
            "required_min_pages": 3,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["summary"]["pages"] == 2
    assert payload["summary"]["page_size"]["label"] == "A4"
    rules = {issue["rule_id"] for issue in payload["issues"]}
    assert "PDF-FONT-NOT-EMBEDDED" in rules
    assert "PDF-PAGE-COUNT" in rules
    assert payload["ok"] is False


@pytest.mark.asyncio()
async def test_audit_latex_pdf_rejects_outside_workspace(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _write_pdf(tmp_path / "outside.pdf")

    resp = await client.post(
        "/api/v1/office/latex/pdf/audit",
        json={"workspace_path": str(workspace), "file_path": str(outside)},
    )

    assert resp.status_code == 400
