"""Workspace MCP Server：远程路径校验（LocalBridge files.cjs parts/resolve 对齐）。"""

from __future__ import annotations

import os

import pytest

from backend.remote_mcp.remote_path import RemotePathError, is_hidden_entry, resolve, split_relative


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("//", encoding="utf-8")
    (tmp_path / ".env").write_text("K=V", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "bad",
    ["", "/etc/passwd", "\\\\server\\share", "C:/x", "C:x", "a:stream", "a/../b", "..",
     "a//b", "a/", "a\x00b", "a\nb", "dir./x", "x ", "nul", "COM1.txt", "lpt9", "a" * 1001],
)
def test_split_relative_rejects(bad):
    with pytest.raises(RemotePathError) as exc:
        split_relative(bad)
    assert str(exc.value).startswith("PATH_DENIED")


@pytest.mark.parametrize(
    ("good", "parts"),
    [(".", []), ("src", ["src"]), ("./src/app.py", ["src", "app.py"]), ("src\\app.py", ["src", "app.py"]),
     ("con_utils.py", ["con_utils.py"]), (".gitignore", [".gitignore"])],
)
def test_split_relative_accepts(good, parts):
    assert split_relative(good) == parts


def test_resolve_inside_workspace(ws):
    assert resolve(str(ws), "src/app.py") == os.path.realpath(str(ws / "src" / "app.py"))
    assert resolve(str(ws), ".") == os.path.realpath(str(ws))


@pytest.mark.parametrize("path", [".git/config", ".GIT/config", ".env", ".env.local", "a/.ssh/id_rsa", ".aws/config"])
def test_resolve_protected(ws, path):
    with pytest.raises(RemotePathError):
        resolve(str(ws), path)


def test_node_modules_read_ok_write_denied(ws):
    assert resolve(str(ws), "node_modules/lib.js")
    with pytest.raises(RemotePathError):
        resolve(str(ws), "node_modules/lib.js", write=True)


def test_resolve_missing_and_may_create(ws):
    with pytest.raises(RemotePathError):
        resolve(str(ws), "src/new.py")
    assert resolve(str(ws), "src/new.py", write=True, may_create=True).endswith("new.py")
    with pytest.raises(RemotePathError):  # 中间目录必须存在
        resolve(str(ws), "nodir/new.py", write=True, may_create=True)


def test_resolve_rejects_symlink_inside_workspace(ws):
    link = ws / "link"
    try:
        os.symlink(str(ws / "src"), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted")
    with pytest.raises(RemotePathError) as exc:
        resolve(str(ws), "link/app.py")
    assert "symlink" in str(exc.value)


def test_hidden_entries():
    assert is_hidden_entry(".git")
    assert is_hidden_entry(".env")
    assert is_hidden_entry("id_rsa")
    assert is_hidden_entry("nul")
    assert not is_hidden_entry("src")
    assert not is_hidden_entry(".env.example")
