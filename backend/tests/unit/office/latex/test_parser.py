"""LaTeX 项目解析器契约测试（TDD RED）。

覆盖：元数据、章节、段落、公式、列表、图、表、引用、标签/交叉引用、
参考文献、include 递归/循环/越界、未知命令降级、注释与转义、行号锚点。
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from backend.office.latex.parser import parse_latex_project

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _blocks(doc, block_type: str):
    return [block for block in doc.blocks if block.type == block_type]


def _warn_codes(doc):
    return {warning.code for warning in doc.warnings}


def test_parse_metadata_abstract_keywords_and_sections(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "paper.tex",
        r"""
\documentclass[11pt]{article}
\title{A \textbf{Great} Paper}
\author{Alice \and Bob}
\affil{Example University}
\date{2026}
\begin{document}
\maketitle
\begin{abstract}
This is an abstract with $E=mc^2$.
\end{abstract}
\keywords{LaTeX, preview}
\section{Introduction}
Hello \textbf{world} and \emph{friends}.
\subsection{Details}
More text.
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    assert doc.metadata.document_class == "article"
    assert doc.metadata.title == "A Great Paper"
    assert doc.metadata.authors == ["Alice", "Bob"]
    assert doc.metadata.affiliations == ["Example University"]
    assert "E=mc^2" in (doc.metadata.abstract or "")
    assert doc.metadata.keywords == ["LaTeX", "preview"]

    headings = _blocks(doc, "heading")
    assert [(h.level, h.text) for h in headings] == [
        (1, "Introduction"),
        (2, "Details"),
    ]
    paragraphs = _blocks(doc, "paragraph")
    assert any("**world**" in p.text and "*friends*" in p.text for p in paragraphs)


def test_parse_inline_and_display_math(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "math.tex",
        r"""
\documentclass{article}
\begin{document}
Inline $a+b$ math.
\[
E = mc^2
\]
\begin{equation}
\label{eq:one}
x = y
\end{equation}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    assert any("$a+b$" in p.text for p in _blocks(doc, "paragraph"))
    equations = _blocks(doc, "equation")
    assert [e.latex.strip() for e in equations] == ["E = mc^2", "x = y"]
    assert equations[1].label == "eq:one"


def test_parse_lists(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "list.tex",
        r"""
\documentclass{article}
\begin{document}
\begin{itemize}
\item One
\item Two with $x$
\end{itemize}
\begin{enumerate}
\item First
\end{enumerate}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    lists = _blocks(doc, "list")
    assert len(lists) == 2
    assert lists[0].ordered is False
    assert [item.text for item in lists[0].items] == ["One", "Two with $x$"]
    assert lists[1].ordered is True
    assert [item.text for item in lists[1].items] == ["First"]


def test_parse_figure_table_and_embedded_image(tmp_path: Path) -> None:
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "arch.png").write_bytes(_PNG_1X1)
    main = _write(
        tmp_path,
        "objects.tex",
        r"""
\documentclass{article}
\begin{document}
\begin{figure}
\includegraphics[width=0.5\textwidth]{figs/arch.png}
\caption{Architecture}
\label{fig:arch}
\end{figure}
\begin{table}
\caption{Results}
\label{tab:res}
\begin{tabular}{ll}
A & B \\
1 & 2 \\
\end{tabular}
\end{table}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    figures = _blocks(doc, "figure")
    assert len(figures) == 1
    assert figures[0].caption == "Architecture"
    assert figures[0].label == "fig:arch"
    assert figures[0].src is not None
    assert figures[0].src.startswith("data:image/png;base64,")

    tables = _blocks(doc, "table")
    assert len(tables) == 1
    assert tables[0].headers == ["A", "B"]
    assert tables[0].rows == [["1", "2"]]
    assert tables[0].caption == "Results"
    assert tables[0].label == "tab:res"


def test_parse_citations_refs_and_thebibliography(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "cite.tex",
        r"""
\documentclass{article}
\begin{document}
\section{Intro}\label{sec:intro}
See \cite{knuth84} and Figure~\ref{fig:one}.
\begin{thebibliography}{9}
\bibitem{knuth84} D. Knuth. The TeXbook. 1984.
\end{thebibliography}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    paragraph = _blocks(doc, "paragraph")[0]
    assert "[knuth84]" in paragraph.text
    assert "[fig:one]" in paragraph.text
    assert "fig:one" in {
        warning.detail.get("target")
        for warning in doc.warnings
        if warning.code == "undefined_reference"
    }

    bibliography = _blocks(doc, "bibliography")
    assert len(bibliography) == 1
    assert bibliography[0].entries[0]["key"] == "knuth84"
    assert "The TeXbook" in bibliography[0].entries[0]["text"]


def test_parse_bibliography_file(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "refs.bib",
        r"""
@article{knuth84,
  author = {Donald Knuth},
  title = {Literate Programming},
  journal = {The Computer Journal},
  year = {1984},
}
""",
    )
    main = _write(
        tmp_path,
        "paper.tex",
        r"""
\documentclass{article}
\begin{document}
\cite{knuth84}
\bibliography{refs}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    bibliography = _blocks(doc, "bibliography")
    assert len(bibliography) == 1
    assert bibliography[0].entries[0]["key"] == "knuth84"
    assert "Literate Programming" in bibliography[0].entries[0]["text"]


def test_include_recursion_cycle_and_line_anchors(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "sections/intro.tex",
        r"""
\section{Introduction}
Included text.
\input{sections/loop}
""",
    )
    _write(
        tmp_path,
        "sections/loop.tex",
        r"""
Looped text.
\input{sections/intro}
""",
    )
    main = _write(
        tmp_path,
        "main.tex",
        r"""
\documentclass{article}
\begin{document}
\input{sections/intro}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    assert any(h.text == "Introduction" for h in _blocks(doc, "heading"))
    assert any("Included text." in p.text for p in _blocks(doc, "paragraph"))
    assert "include_cycle" in _warn_codes(doc)
    assert _blocks(doc, "heading")[0].anchor is not None
    assert _blocks(doc, "heading")[0].anchor.file.endswith("sections/intro.tex")
    assert _blocks(doc, "heading")[0].anchor.line >= 1


def test_include_path_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.tex"
    outside.write_text("SECRET", encoding="utf-8")
    main = _write(
        tmp_path,
        "main.tex",
        r"""
\documentclass{article}
\begin{document}
\input{../outside-secret}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    assert "include_path_escape" in _warn_codes(doc)
    assert all("SECRET" not in p.text for p in _blocks(doc, "paragraph"))


def test_unknown_command_and_environment_degrade_with_warnings(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "unknown.tex",
        r"""
\documentclass{article}
\begin{document}
\foo{bar} baz.
\begin{unknownenv}
inside unknown
\end{unknownenv}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    paragraph_text = "\n".join(p.text for p in _blocks(doc, "paragraph"))
    assert "bar" in paragraph_text
    assert "unknown_command" in _warn_codes(doc)
    assert "unknown_environment" in _warn_codes(doc)


def test_comments_and_escaped_percent(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "comments.tex",
        r"""
\documentclass{article}
\begin{document}
This is 50\% done. % hidden comment
Second line.
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    paragraph_text = "\n".join(p.text for p in _blocks(doc, "paragraph"))
    assert "50%" in paragraph_text
    assert "hidden comment" not in paragraph_text
    assert "Second line." in paragraph_text


def test_missing_image_warns_without_crashing(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "missing.tex",
        r"""
\documentclass{article}
\begin{document}
\begin{figure}
\includegraphics{figs/missing.png}
\caption{Missing}
\end{figure}
\end{document}
""",
    )

    doc = parse_latex_project(main, root=tmp_path)

    figures = _blocks(doc, "figure")
    assert len(figures) == 1
    assert figures[0].src is None
    assert "missing_image" in _warn_codes(doc)


def test_main_file_missing_raises_parse_error(tmp_path: Path) -> None:
    from backend.office.errors import OfficeFileNotFoundError

    with pytest.raises(OfficeFileNotFoundError):
        parse_latex_project(tmp_path / "nope.tex", root=tmp_path)
