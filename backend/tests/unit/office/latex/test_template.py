"""Tests for LaTeX template profile, filler and validator (L2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.errors import OfficeTemplateFillError
from backend.office.latex.filler import fill_latex_template
from backend.office.latex.template import analyze_latex_template
from backend.office.latex.validator import validate_latex_source

_TEMPLATE = r"""
\documentclass[11pt,twocolumn]{article}
\usepackage{natbib}
\geometry{a4paper,margin=2cm}
\linespread{1.2}
\bibliographystyle{plain}
\title{Old Title}
\author{Old Author}
\begin{document}
\begin{abstract}
Old abstract.
\end{abstract}
\section{Intro}
Keep this text.
<<author_note>>
% TODO: fill funding
\end{document}
"""

_CLS = r"""
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{journal}
\RequirePackage{geometry}
\newcommand{\journalname}[1]{#1}
\newenvironment{keywords}{\bfseries}{\par}
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_analyze_template_extracts_style_macros_and_slots(tmp_path: Path) -> None:
    _write(tmp_path, "journal.cls", _CLS)
    main = _write(tmp_path, "paper.tex", _TEMPLATE)

    profile = analyze_latex_template(main, root=tmp_path)

    assert profile.document_class == "article"
    assert profile.document_options == ["11pt", "twocolumn"]
    assert "geometry" in profile.packages
    assert "natbib" in profile.packages
    assert profile.style["geometry"] == "a4paper,margin=2cm"
    assert profile.style["linespread"] == "1.2"
    assert profile.style["bibliography_style"] == "plain"
    assert profile.style["columns"] == "two"
    assert profile.style["citation_package"] == "natbib"
    assert "journalname" in profile.macros

    slots = {slot.name: slot for slot in profile.slots}
    assert slots["title"].kind == "command_arg"
    assert slots["title"].current_value == "Old Title"
    assert slots["title"].required is True
    assert slots["author"].current_value == "Old Author"
    assert slots["abstract"].kind == "environment_body"
    assert slots["abstract"].current_value == "Old abstract."
    placeholder = next(
        slot
        for slot in profile.slots
        if slot.kind == "placeholder" and "author_note" in slot.name
    )
    assert placeholder.required is True
    assert any(slot.kind == "comment" for slot in profile.slots)


def test_fill_template_preserves_non_slot_source_and_escapes(tmp_path: Path) -> None:
    main = _write(tmp_path, "paper.tex", _TEMPLATE)
    profile = analyze_latex_template(main, root=tmp_path)
    placeholder_name = next(
        slot.name
        for slot in profile.slots
        if slot.kind == "placeholder" and "author_note" in slot.name
    )

    result = fill_latex_template(
        main,
        {
            "title": "New & Title",
            "author": ["Alice", "Bob"],
            "abstract": "New abstract with 50% done.",
            placeholder_name: "Thanks",
        },
        "paper-filled.tex",
        root=tmp_path,
    )

    output = tmp_path / "paper-filled.tex"
    assert result["ok"] is True
    assert result["filled_count"] == 4
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert r"New \& Title" in text
    assert r"Alice \and Bob" in text
    assert r"50\% done" in text
    assert "Thanks" in text
    assert "<<author_note>>" not in text
    assert "Keep this text." in text
    assert "Old Title" in main.read_text(encoding="utf-8")
    assert any("comment" in name for name in result["unfilled_slots"])


def test_fill_template_rejects_missing_required_slots(tmp_path: Path) -> None:
    main = _write(tmp_path, "paper.tex", _TEMPLATE)

    with pytest.raises(OfficeTemplateFillError) as exc:
        fill_latex_template(main, {"title": "Only title"}, "out.tex", root=tmp_path)

    message = str(exc.value)
    assert "author" in message
    assert "abstract" in message


def test_fill_template_refuses_to_overwrite_output(tmp_path: Path) -> None:
    main = _write(tmp_path, "paper.tex", _TEMPLATE)
    (tmp_path / "out.tex").write_text("existing", encoding="utf-8")
    profile = analyze_latex_template(main, root=tmp_path)
    placeholder_name = next(
        slot.name for slot in profile.slots if slot.kind == "placeholder"
    )

    with pytest.raises(OfficeTemplateFillError):
        fill_latex_template(
            main,
            {
                "title": "T",
                "author": "A",
                "abstract": "B",
                placeholder_name: "C",
            },
            "out.tex",
            root=tmp_path,
        )


def test_validator_detects_unbalanced_braces_and_env_mismatch() -> None:
    result = validate_latex_source(r"\begin{a}{unclosed \end{b}")

    codes = {issue["code"] for issue in result["issues"]}
    assert result["ok"] is False
    assert "unbalanced_brace" in codes
    assert "mismatched_environment" in codes


def test_validator_reports_residue_as_warning() -> None:
    result = validate_latex_source(r"<<name>>")

    assert result["ok"] is True
    assert result["issues"][0]["severity"] == "warning"
    assert result["issues"][0]["code"] == "placeholder_residue"
