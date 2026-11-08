"""sage_docs.paths 单元测试。"""

from pathlib import Path

import pytest

from backend.services.sage_docs import paths

pytestmark = pytest.mark.unit


def _make_docs(root: Path) -> Path:
    (root / "user-manual" / "sub").mkdir(parents=True)
    (root / "user-manual" / "01-intro.md").write_text("# 简介\n", encoding="utf-8")
    (root / "user-manual" / "sub" / "02-nested.md").write_text("# 嵌套\n", encoding="utf-8")
    (root / "technical").mkdir()
    (root / "technical" / "README.md").write_text("# 技术\n", encoding="utf-8")
    return root


def test_resolve_docs_root_env_override(tmp_path, monkeypatch):
    root = _make_docs(tmp_path / "docs")
    monkeypatch.setenv(paths.DOCS_ENV_VAR, str(root))
    assert paths.resolve_docs_root() == root.resolve()


def test_resolve_docs_root_env_missing_falls_through(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DOCS_ENV_VAR, str(tmp_path / "missing"))
    resolved = paths.resolve_docs_root()
    assert resolved is None or resolved.is_dir()


def test_resolve_index_dir_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom-index"
    monkeypatch.setenv(paths.INDEX_ENV_VAR, str(target))
    assert paths.resolve_index_dir() == target


def test_resolve_index_dir_uses_user_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.INDEX_ENV_VAR, raising=False)
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    assert paths.resolve_index_dir() == tmp_path / "sage-docs-index"


def test_resolve_index_dir_falls_back_to_home(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.INDEX_ENV_VAR, raising=False)
    monkeypatch.delenv("SAGE_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.resolve_index_dir() == tmp_path / ".sage" / "sage-docs-index"


def test_iter_doc_files_takes_user_manual_and_whitelisted_technical(tmp_path):
    root = _make_docs(tmp_path / "docs")
    (root / "technical" / "999-not-whitelisted.md").write_text("# 其它\n", encoding="utf-8")

    names = sorted(p.relative_to(root).as_posix() for p in paths.iter_doc_files(root))

    assert names == [
        "technical/README.md",
        "user-manual/01-intro.md",
        "user-manual/sub/02-nested.md",
    ]


def test_iter_doc_files_empty_when_dirs_missing(tmp_path):
    assert paths.iter_doc_files(tmp_path / "nothing-here") == []
