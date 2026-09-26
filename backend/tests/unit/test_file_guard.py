"""LocalBridge P0：文件写入乐观锁 + 凭据路径守卫。"""

from __future__ import annotations

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.edit_tool import EditTool
from backend.tools.file_guard import (
    ALLOW_SENSITIVE_ENV,
    check_expected_version,
    compute_file_version,
    sensitive_path_reason,
)
from backend.tools.file_tool import ReadFileTool, WriteFileTool
from backend.tools.patch_tool import ApplyPatchTool


@pytest.fixture(autouse=True)
def _guard_enabled(monkeypatch):
    monkeypatch.delenv(ALLOW_SENSITIVE_ENV, raising=False)


def _policy(root) -> ToolPolicy:
    return ToolPolicy(workspace_root=str(root))


# ── 版本号 ───────────────────────────────────────────────────────────


def test_read_file_returns_version_matching_disk_bytes(tmp_path):
    target = tmp_path / "a.txt"
    target.write_bytes(b"hello\r\nworld\n")
    result = ReadFileTool().execute(path=str(target), offset=2, limit=1)
    assert result.success
    assert result.content["version"] == compute_file_version(str(target))
    assert result.content["version"].startswith("sha256:")


def test_write_file_with_stale_version_is_rejected(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    stale = compute_file_version(str(target))
    target.write_text("v2 by someone else", encoding="utf-8")

    tool = WriteFileTool(policy=_policy(tmp_path))
    result = tool.execute(path=str(target), content="mine", expected_version=stale)

    assert not result.success
    assert "version_conflict" in result.error
    assert target.read_text(encoding="utf-8") == "v2 by someone else"


def test_write_file_with_current_version_succeeds_and_returns_new_version(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    current = compute_file_version(str(target))

    result = WriteFileTool(policy=_policy(tmp_path)).execute(
        path=str(target), content="v2", expected_version=current
    )

    assert result.success
    assert result.content["version"] == compute_file_version(str(target))
    assert result.content["version"] != current


def test_write_file_new_token_refuses_to_overwrite(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("exists", encoding="utf-8")
    tool = WriteFileTool(policy=_policy(tmp_path))

    assert "version_conflict" in tool.execute(
        path=str(target), content="x", expected_version="new"
    ).error
    fresh = tmp_path / "b.txt"
    assert tool.execute(path=str(fresh), content="x", expected_version="new").success


def test_write_file_without_version_keeps_legacy_behaviour(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    assert WriteFileTool(policy=_policy(tmp_path)).execute(path=str(target), content="v2").success


@pytest.mark.parametrize("bad", ["", "abc", "sha256:xyz", "sha256:" + "0" * 63, 123])
def test_invalid_expected_version_rejected(tmp_path, bad):
    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    result = check_expected_version(str(target), bad)
    assert result is not None
    assert "invalid_expected_version" in result.error


def test_expected_version_is_case_insensitive(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    assert check_expected_version(str(target), compute_file_version(str(target)).upper().replace("SHA256", "sha256")) is None


def test_edit_file_version_conflict_and_success(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    tool = EditTool(policy=_policy(tmp_path))

    stale = "sha256:" + "0" * 64
    conflict = tool.execute(
        file_path=str(target), old_string="x = 1", new_string="x = 2", expected_version=stale
    )
    assert not conflict.success
    assert "version_conflict" in conflict.error
    assert target.read_text(encoding="utf-8") == "x = 1\n"

    ok = tool.execute(
        file_path=str(target),
        old_string="x = 1",
        new_string="x = 2",
        expected_version=compute_file_version(str(target)),
    )
    assert ok.success
    assert ok.content["version"] == compute_file_version(str(target))


def test_apply_patch_conflict_writes_nothing(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("alpha\n", encoding="utf-8")
    b.write_text("beta\n", encoding="utf-8")
    result = ApplyPatchTool(policy=_policy(tmp_path)).execute(
        patches=[
            {"file_path": "a.txt", "old_string": "alpha", "new_string": "A",
             "expected_version": compute_file_version(str(a))},
            {"file_path": "b.txt", "old_string": "beta", "new_string": "B",
             "expected_version": "sha256:" + "f" * 64},
        ]
    )
    assert not result.success
    assert "patches[1]" in result.error
    assert "version_conflict" in result.error
    assert a.read_text(encoding="utf-8") == "alpha\n"
    assert b.read_text(encoding="utf-8") == "beta\n"


def test_apply_patch_chained_patches_check_original_version(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("one two\n", encoding="utf-8")
    original = compute_file_version(str(a))
    result = ApplyPatchTool(policy=_policy(tmp_path)).execute(
        patches=[
            {"file_path": "a.txt", "old_string": "one", "new_string": "1", "expected_version": original},
            {"file_path": "a.txt", "old_string": "two", "new_string": "2", "expected_version": original},
        ]
    )
    assert result.success, result.error
    assert a.read_text(encoding="utf-8") == "1 2\n"
    assert result.content["files_changed"][0]["version"] == compute_file_version(str(a))


# ── 凭据路径 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "proj/.env.local",
        "proj/.env.production",
        "C:\\Users\\me\\.ssh\\id_rsa",
        "/home/me/.ssh/id_ed25519",
        "/home/me/.ssh/my_custom_key",
        "certs/server.pem",
        "certs/server.KEY",
        "store.pfx",
        "~/.git-credentials",
        "~/.netrc",
        "~/.aws/credentials",
        "~/.docker/config.json",
        "~/.kube/config",
        "vault.kdbx",
    ],
)
def test_sensitive_paths_detected(path):
    assert sensitive_path_reason(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "proj/.env.sample",
        ".env.template",
        "/home/me/.ssh/id_rsa.pub",
        "/home/me/.ssh/known_hosts",
        "/home/me/.ssh/config",
        "src/environment.py",
        "docs/keys.md",
        "config.json",
        "kube/config",
        "monkey.txt",
    ],
)
def test_non_sensitive_paths_allowed(path):
    assert sensitive_path_reason(path) is None


def test_read_file_blocks_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_KEY=secret", encoding="utf-8")
    result = ReadFileTool().execute(path=str(env))
    assert not result.success
    assert "sensitive_path_blocked" in result.error
    assert "secret" not in result.error


def test_write_and_edit_and_patch_block_sensitive(tmp_path):
    key = tmp_path / "server.pem"
    key.write_text("-----BEGIN-----", encoding="utf-8")
    policy = _policy(tmp_path)
    assert "sensitive_path_blocked" in WriteFileTool(policy=policy).execute(
        path=str(key), content="x"
    ).error
    assert "sensitive_path_blocked" in EditTool(policy=policy).execute(
        file_path=str(key), old_string="BEGIN", new_string="END"
    ).error
    assert "sensitive_path_blocked" in ApplyPatchTool(policy=policy).execute(
        patches=[{"file_path": "server.pem", "old_string": "BEGIN", "new_string": "END"}]
    ).error
    assert key.read_text(encoding="utf-8") == "-----BEGIN-----"


def test_env_override_disables_guard(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("A=1", encoding="utf-8")
    monkeypatch.setenv(ALLOW_SENSITIVE_ENV, "1")
    assert ReadFileTool().execute(path=str(env)).success


# ── M0：段尾点/空格、ADS、保留名、.git、扩展目录规则 ─────────────────


@pytest.mark.parametrize(
    "path",
    [".env ", ".env.", "id_rsa.", "id_rsa ", "x.pem.", "a/.ssh./x", "a/.aws/config",
     "a/.azure/accessTokens.json", "deploy/credentials", "credentials."],
)
def test_trailing_dot_space_and_dir_rules_detected(path):
    assert sensitive_path_reason(path) is not None


@pytest.mark.parametrize(
    "path",
    ["a.txt:hidden", "dir/nul", "dir/NUL.txt", "com1.log", "lpt9", "bad./x.txt",
     "name .txt ", ".git/hooks/pre-commit", "sub/.git/config"],
)
def test_invalid_write_paths_rejected(tmp_path, path):
    from backend.tools.file_guard import check_sensitive_path

    result = check_sensitive_path(path, "写入", write=True)
    assert result is not None
    assert "path_denied" in result.error


@pytest.mark.parametrize("path", ["C:/work/a.txt", "C:\\work\\.gitignore", "src/con_utils.py", "a/../b.txt"])
def test_valid_write_paths_allowed(path):
    from backend.tools.file_guard import check_sensitive_path

    assert check_sensitive_path(path, "写入", write=True) is None


def test_git_dir_readable_but_not_writable(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    cfg = git / "config"
    cfg.write_text("[core]", encoding="utf-8")
    assert ReadFileTool().execute(path=str(cfg)).success
    result = WriteFileTool(policy=_policy(tmp_path)).execute(path=str(cfg), content="x")
    assert "path_denied" in result.error


def test_path_denied_ignores_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(ALLOW_SENSITIVE_ENV, "1")
    result = WriteFileTool(policy=_policy(tmp_path)).execute(
        path=str(tmp_path / "a.txt:ads"), content="x"
    )
    assert not result.success
    assert "path_denied" in result.error


# ── M0：原子写入 + 写互斥 ───────────────────────────────────────────


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    assert WriteFileTool(policy=_policy(tmp_path)).execute(path=str(target), content="v2").success
    assert EditTool(policy=_policy(tmp_path)).execute(
        file_path=str(target), old_string="v2", new_string="v3"
    ).success
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt"]
    assert target.read_text(encoding="utf-8") == "v3"


def test_atomic_write_recheck_detects_concurrent_change(tmp_path):
    from backend.tools.file_guard import atomic_write

    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    version = compute_file_version(str(target))

    def writer(temp):
        # 模拟写临时文件期间，他人改动了目标文件
        target.write_text("someone else", encoding="utf-8")
        with open(temp, "w", encoding="utf-8") as f:
            f.write("mine")

    result = atomic_write(str(target), writer, version)
    assert result is not None
    assert "version_conflict" in result.error
    assert target.read_text(encoding="utf-8") == "someone else"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt"]


def test_file_write_lock_rejects_concurrent_writer(tmp_path):
    from backend.tools.file_guard import file_write_lock

    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    with file_write_lock([str(target)]) as outer:
        assert outer is None
        busy = WriteFileTool(policy=_policy(tmp_path)).execute(path=str(target), content="x")
        assert not busy.success
        assert "file_busy" in busy.error
    assert WriteFileTool(policy=_policy(tmp_path)).execute(path=str(target), content="x").success


def test_write_file_preserves_text_mode_newlines(tmp_path):
    import os

    target = tmp_path / "a.txt"
    WriteFileTool(policy=_policy(tmp_path)).execute(path=str(target), content="a\nb\n")
    assert target.read_bytes() == ("a" + os.linesep + "b" + os.linesep).encode()
