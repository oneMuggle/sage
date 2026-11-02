"""Tests for optional LaTeX compile adapter (stubbed engine)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.office.errors import OfficeParseError
from backend.office.latex import compile as compile_mod
from backend.office.latex.compile import compile_latex, detect_engines

_CLEAN = r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
Hello.
\end{document}
"""

_UNSAFE = r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\write18{echo nope}
\end{document}
"""


def _workspace(tmp_path: Path, text: str = _CLEAN) -> tuple:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    main = workspace / "paper.tex"
    main.write_text(text, encoding="utf-8")
    return workspace, main


def _engine(monkeypatch: pytest.MonkeyPatch, engine: str = "latexmk") -> None:
    monkeypatch.setattr(
        compile_mod.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == engine else None,
    )


def _fake_run(monkeypatch: pytest.MonkeyPatch, *, raise_timeout: bool = False):
    calls = []

    def fake_run(cmd, cwd, env, shell, timeout, capture_output, text, check=None):
        calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        if raise_timeout:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
        Path(cwd, "paper.pdf").write_bytes(b"%PDF-1.4")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(compile_mod.subprocess, "run", fake_run)
    return calls


def test_detect_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    _engine(monkeypatch, "latexmk")
    engines = detect_engines()
    assert engines == [{"name": "latexmk", "path": "/usr/bin/latexmk"}]


def test_compile_without_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, main = _workspace(tmp_path)
    monkeypatch.setattr(compile_mod.shutil, "which", lambda name: None)

    result = compile_latex(main, root=workspace, output_filename="out.pdf")

    assert result["ok"] is False
    assert result["code"] == "no_engine"


def test_compile_refuses_unsafe_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, main = _workspace(tmp_path, _UNSAFE)
    _engine(monkeypatch)
    calls = _fake_run(monkeypatch)

    result = compile_latex(main, root=workspace, output_filename="out.pdf")

    assert result["ok"] is False
    assert result["code"] == "audit_failed"
    assert calls == []
    assert not (workspace / "out.pdf").exists()


def test_compile_success_copies_pdf_and_uses_safe_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, main = _workspace(tmp_path)
    _engine(monkeypatch)
    calls = _fake_run(monkeypatch)

    result = compile_latex(main, root=workspace, output_filename="out.pdf")

    assert result["ok"] is True
    assert (workspace / "out.pdf").is_file()
    assert calls
    cmd = calls[0]["cmd"]
    assert "-no-shell-escape" in cmd
    assert "-halt-on-error" in cmd
    assert calls[0]["env"]["openin_any"] == "p"
    assert calls[0]["env"]["openout_any"] == "p"


def test_compile_refuses_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, main = _workspace(tmp_path)
    (workspace / "out.pdf").write_bytes(b"existing")
    _engine(monkeypatch)

    with pytest.raises(OfficeParseError):
        compile_latex(main, root=workspace, output_filename="out.pdf")


def test_compile_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, main = _workspace(tmp_path)
    _engine(monkeypatch)
    _fake_run(monkeypatch, raise_timeout=True)

    result = compile_latex(main, root=workspace, output_filename="out.pdf", timeout_s=1)

    assert result["ok"] is False
    assert result["code"] == "timeout"
