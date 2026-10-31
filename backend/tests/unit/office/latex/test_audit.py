"""Tests for deterministic LaTeX source audit (L3a)."""

from __future__ import annotations

from pathlib import Path

from backend.office.latex.audit import audit_latex_file

_CLEAN = r"""
\documentclass{article}
\title{Paper}
\author{Alice}
\begin{document}
\begin{abstract}
Abstract.
\end{abstract}
\section{Introduction}\label{sec:intro}
See \ref{sec:intro} and \cite{knuth84}.
\begin{figure}
\caption{Architecture}
\label{fig:one}
\end{figure}
\begin{table}
\caption{Results}
\label{tab:one}
\begin{tabular}{ll}
A & B \\
1 & 2 \\
\end{tabular}
\end{table}
\begin{thebibliography}{9}
\bibitem{knuth84} D. Knuth. 1984.
\end{thebibliography}
\end{document}
"""


def _write(tmp_path: Path, text: str, name: str = "paper.tex") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _rule_ids(result) -> set:
    return {issue["rule_id"] for issue in result["issues"]}


def test_clean_document_has_no_errors(tmp_path: Path) -> None:
    result = audit_latex_file(_write(tmp_path, _CLEAN), root=tmp_path)

    assert result["ok"] is True
    assert result["summary"]["severity"]["error"] == 0
    assert "LATEX-CITE-UNDEFINED" not in _rule_ids(result)
    assert "LATEX-REF-UNDEFINED" not in _rule_ids(result)


def test_missing_metadata_warns(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        r"""
\documentclass{article}
\begin{document}
Text.
\end{document}
""",
    )

    result = audit_latex_file(main, root=tmp_path)

    rules = _rule_ids(result)
    assert "LATEX-META-TITLE" in rules
    assert "LATEX-META-AUTHOR" in rules
    assert "LATEX-META-ABSTRACT" in rules
    assert result["ok"] is True


def test_missing_documentclass_is_error(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        r"""
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\end{document}
""",
    )

    result = audit_latex_file(main, root=tmp_path)

    assert "LATEX-DOC-CLASS" in _rule_ids(result)
    assert result["ok"] is False


def test_undefined_citation_is_error(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\cite{missing}
\begin{thebibliography}{9}
\bibitem{known} Known.
\end{thebibliography}
\end{document}
""",
    )

    result = audit_latex_file(main, root=tmp_path)

    issue = next(i for i in result["issues"] if i["rule_id"] == "LATEX-CITE-UNDEFINED")
    assert issue["severity"] == "error"
    assert issue["evidence"]["key"] == "missing"
    assert issue["anchor"]["file"] == "paper.tex"


def test_undefined_reference_is_error(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
See \ref{nope}.
\end{document}
""",
    )

    result = audit_latex_file(main, root=tmp_path)

    assert "LATEX-REF-UNDEFINED" in _rule_ids(result)
    assert result["ok"] is False


def test_figure_without_caption_or_label_warns(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\begin{figure}
\end{figure}
\end{document}
""",
    )

    result = audit_latex_file(main, root=tmp_path)

    assert "LATEX-FIG-CAPTION" in _rule_ids(result)
    assert "LATEX-FIG-LABEL" in _rule_ids(result)
    assert result["ok"] is True


def test_duplicate_label_and_todo_warn(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\section{One}\label{dup}
\section{Two}\label{dup}
% TODO: fix this
<<name>>
\end{document}
""",
    )

    result = audit_latex_file(main, root=tmp_path)

    rules = _rule_ids(result)
    assert "LATEX-LABEL-DUPLICATE" in rules
    assert "LATEX-TODO" in rules


def test_unsafe_commands_are_errors(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\write18{rm -rf /}
\input{/etc/passwd}
\end{document}
""",
    )

    result = audit_latex_file(main, root=tmp_path)

    unsafe = [i for i in result["issues"] if i["rule_id"] == "LATEX-UNSAFE-COMMAND"]
    assert len(unsafe) >= 2
    assert all(i["severity"] == "error" for i in unsafe)
    assert result["ok"] is False


def test_required_sections_are_configurable(tmp_path: Path) -> None:
    main = _write(tmp_path, _CLEAN)

    result = audit_latex_file(
        main,
        root=tmp_path,
        required_sections=["Introduction", "Conclusion"],
    )

    missing = [
        i for i in result["issues"] if i["rule_id"] == "LATEX-SECTION-REQUIRED"
    ]
    assert [i["evidence"]["required_section"] for i in missing] == ["Conclusion"]
    assert result["ok"] is False


def test_include_path_escape_is_error(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\input{../outside}
\end{document}
""",
    )

    result = audit_latex_file(main, root=tmp_path)

    assert "LATEX-INCLUDE" in _rule_ids(result)
    assert result["ok"] is False
