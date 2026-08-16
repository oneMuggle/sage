"""M2 glob_search / grep_search 工具单元测试。

移植 claw-code file_ops.rs 的搜索语义：mtime 倒序、结果上限、
忽略目录、二进制嗅探跳过、非法正则干净报错、永不抛异常。
"""

from __future__ import annotations

import os

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.search_tools import (
    GLOB_MAX_RESULTS,
    GREP_CONTENT_MAX_MATCHES,
    GREP_FILES_MAX_MATCHES,
    GREP_MAX_LINE_LENGTH,
    GREP_MAX_PATTERN_LENGTH,
    GlobSearchTool,
    GrepSearchTool,
)

pytestmark = pytest.mark.unit


def _touch(path, text: str = "", mtime: float = 0.0):
    """创建文件并可选设置 mtime（用于排序断言）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


# ---------------------------------------------------------------------------
# glob_search
# ---------------------------------------------------------------------------


def test_glob_returns_files_sorted_by_mtime_desc(tmp_path):
    """匹配结果按修改时间倒序（最新在前）。"""
    # Arrange
    _touch(tmp_path / "old.py", mtime=1000)
    _touch(tmp_path / "mid.py", mtime=2000)
    newest = _touch(tmp_path / "new.py", mtime=3000)
    tool = GlobSearchTool()

    # Act
    result = tool.execute(pattern="*.py", path=str(tmp_path))

    # Assert
    assert result.success is True
    files = result.content["files"]
    assert len(files) == 3
    assert files[0] == str(newest)
    assert result.content["truncated"] is False


def test_glob_pattern_without_slash_matches_basename_at_any_depth(tmp_path):
    """不含路径分隔符的 pattern 按 basename 匹配任意深度文件。"""
    # Arrange
    _touch(tmp_path / "a" / "b" / "deep.py")
    _touch(tmp_path / "top.py")
    _touch(tmp_path / "skip.txt")
    tool = GlobSearchTool()

    # Act
    result = tool.execute(pattern="*.py", path=str(tmp_path))

    # Assert
    names = sorted(os.path.basename(f) for f in result.content["files"])
    assert names == ["deep.py", "top.py"]


def test_glob_pattern_with_slash_matches_relative_path(tmp_path):
    """含分隔符的 pattern 按相对路径匹配。"""
    # Arrange
    _touch(tmp_path / "src" / "app.ts")
    _touch(tmp_path / "lib" / "app.ts")
    tool = GlobSearchTool()

    # Act
    result = tool.execute(pattern="src/*.ts", path=str(tmp_path))

    # Assert
    assert result.content["num_files"] == 1
    assert result.content["files"][0].endswith(os.path.join("src", "app.ts"))


def test_glob_caps_results_and_flags_truncated(tmp_path):
    """超过 200 条 → 截断并置 truncated=True，total_matches 记全量。"""
    # Arrange
    for i in range(GLOB_MAX_RESULTS + 5):
        _touch(tmp_path / f"f{i:03d}.txt")
    tool = GlobSearchTool()

    # Act
    result = tool.execute(pattern="*.txt", path=str(tmp_path))

    # Assert
    assert result.success is True
    assert result.content["truncated"] is True
    assert len(result.content["files"]) == GLOB_MAX_RESULTS
    assert result.content["total_matches"] == GLOB_MAX_RESULTS + 5


@pytest.mark.parametrize(
    "ignored_dir",
    ["node_modules", ".git", "__pycache__", "dist"],
)
def test_glob_skips_default_ignored_dirs(tmp_path, ignored_dir):
    """默认跳过 node_modules / .git / __pycache__ / dist。"""
    # Arrange
    _touch(tmp_path / ignored_dir / "inner.txt")
    _touch(tmp_path / "visible.txt")
    tool = GlobSearchTool()

    # Act
    result = tool.execute(pattern="*.txt", path=str(tmp_path))

    # Assert
    names = [os.path.basename(f) for f in result.content["files"]]
    assert names == ["visible.txt"]


def test_glob_defaults_root_to_policy_workspace_root(tmp_path, monkeypatch):
    """缺省 path → 取 policy.workspace_root（而非 cwd）。"""
    # Arrange: cwd 切到无关目录，workspace 绑定到 tmp/ws
    workspace = tmp_path / "ws"
    _touch(workspace / "bound.py")
    monkeypatch.chdir(tmp_path)
    tool = GlobSearchTool(policy=ToolPolicy(workspace_root=str(workspace)))

    # Act
    result = tool.execute(pattern="*.py")

    # Assert
    assert result.success is True
    assert [os.path.basename(f) for f in result.content["files"]] == ["bound.py"]
    assert result.content["root"] == str(workspace.resolve())


def test_glob_nonexistent_path_returns_error_result(tmp_path):
    """搜索路径不存在 → success=False，不抛异常。"""
    # Act
    result = GlobSearchTool().execute(pattern="*", path=str(tmp_path / "missing"))

    # Assert
    assert result.success is False
    assert "搜索路径不存在" in result.error


def test_glob_empty_pattern_rejected(tmp_path):
    """空 pattern → 干净错误。"""
    # Act / Assert
    for bad in ("", "   "):
        result = GlobSearchTool().execute(pattern=bad, path=str(tmp_path))
        assert result.success is False
        assert "pattern 不能为空" in result.error


def test_glob_absolute_pattern_matches_on_absolute_path(tmp_path):
    """绝对 pattern 按绝对路径匹配。

    FIX-8 回归：拼出的绝对路径也归一成 "/" 分隔——Linux 上本测试只走通
    该分支，Windows 上 os.path.join 的 "\\" 分隔符归一化是同一段代码保障的。
    """
    # Arrange
    _touch(tmp_path / "abs.py")
    _touch(tmp_path / "abs.txt")

    # Act
    result = GlobSearchTool().execute(pattern=f"{tmp_path}/*.py", path=str(tmp_path))

    # Assert
    assert result.success is True
    assert [os.path.basename(f) for f in result.content["files"]] == ["abs.py"]


def test_glob_rejects_unknown_kwargs(tmp_path):
    """FIX-2 回归：拼错的参数名 → 干净错误，不被 **kwargs 静默吞掉。"""
    # Act —— 模拟 LLM 把 path 拼成 pth
    result = GlobSearchTool().execute(pattern="*.py", path=str(tmp_path), pth="/x")

    # Assert
    assert result.success is False
    assert "未知参数" in result.error
    assert "pth" in result.error


# ---------------------------------------------------------------------------
# grep_search
# ---------------------------------------------------------------------------


def test_grep_content_mode_returns_file_line_text(tmp_path):
    """content 模式返回 'file:line:text' 格式匹配行。"""
    # Arrange
    target = _touch(tmp_path / "code.py", "alpha\nNEEDLE here\nbeta\n")
    tool = GrepSearchTool()

    # Act
    result = tool.execute(pattern="NEEDLE", path=str(tmp_path), output_mode="content")

    # Assert
    assert result.success is True
    assert result.content["mode"] == "content"
    assert result.content["matches"] == [f"{target}:2:NEEDLE here"]
    assert result.content["num_matches"] == 1
    assert result.content["files_scanned"] == 1


def test_grep_files_mode_returns_paths_only(tmp_path):
    """files 模式只返回命中文件路径，不含行内容。"""
    # Arrange
    hit = _touch(tmp_path / "hit.txt", "match me\n")
    _touch(tmp_path / "miss.txt", "nothing\n")
    tool = GrepSearchTool()

    # Act
    result = tool.execute(pattern="match", path=str(tmp_path), output_mode="files")

    # Assert
    assert result.content["mode"] == "files"
    assert result.content["files"] == [str(hit)]
    assert "matches" not in result.content


def test_grep_case_insensitive_option(tmp_path):
    """case_insensitive=true → 大小写不敏感匹配。"""
    # Arrange
    _touch(tmp_path / "c.txt", "Hello World\n")
    tool = GrepSearchTool()

    # Act / Assert
    sensitive = tool.execute(pattern="hello", path=str(tmp_path))
    assert sensitive.content["num_matches"] == 0
    insensitive = tool.execute(pattern="hello", path=str(tmp_path), case_insensitive=True)
    assert insensitive.content["num_matches"] == 1


def test_grep_invalid_regex_returns_clean_error(tmp_path):
    """非法正则 → success=False 干净错误，永不抛异常。"""
    # Act
    result = GrepSearchTool().execute(pattern="(unclosed", path=str(tmp_path))

    # Assert
    assert result.success is False
    assert "非法正则表达式" in result.error


def test_grep_invalid_output_mode_rejected(tmp_path):
    """output_mode 非法取值 → 干净错误。"""
    # Act
    result = GrepSearchTool().execute(pattern="x", path=str(tmp_path), output_mode="count")

    # Assert
    assert result.success is False
    assert "content 或 files" in result.error


def test_grep_skips_binary_files_via_nul_sniff(tmp_path):
    """含 NUL 字节的二进制文件被跳过且计入 skipped_binary。"""
    # Arrange
    _touch(tmp_path / "text.txt", "needle\n")
    (tmp_path / "blob.bin").write_bytes(b"\x00needle\x00binary")
    tool = GrepSearchTool()

    # Act
    result = tool.execute(pattern="needle", path=str(tmp_path))

    # Assert
    assert result.content["num_matches"] == 1  # 只命中文本文件
    assert result.content["skipped_binary"] == 1
    assert result.content["files_scanned"] == 1


def test_grep_searches_utf16_bom_file_as_text(tmp_path):
    """UTF-16 BOM 文件按文本搜索（NUL 嗅探不误报，复用 file_tool BOM 识别）。"""
    # Arrange
    (tmp_path / "legacy.reg").write_bytes("findme=yes\n".encode("utf-16"))
    tool = GrepSearchTool()

    # Act
    result = tool.execute(pattern="findme", path=str(tmp_path))

    # Assert
    assert result.content["num_matches"] == 1
    assert result.content["skipped_binary"] == 0


def test_grep_content_mode_caps_matches_at_100(tmp_path):
    """content 模式匹配行超 100 → 截断，num_matches 仍记全量。"""
    # Arrange: 单文件 150 行全部命中
    _touch(tmp_path / "many.txt", "\n".join(f"hit line {i}" for i in range(150)) + "\n")
    tool = GrepSearchTool()

    # Act
    result = tool.execute(pattern="hit", path=str(tmp_path))

    # Assert
    assert result.content["truncated"] is True
    assert len(result.content["matches"]) == GREP_CONTENT_MAX_MATCHES
    assert result.content["num_matches"] == 150


def test_grep_files_mode_caps_at_200_and_flags_truncated(tmp_path):
    """files 模式命中文件超 200 → 截断并标记。"""
    # Arrange
    for i in range(GREP_FILES_MAX_MATCHES + 3):
        _touch(tmp_path / f"m{i:03d}.txt", "token\n")
    tool = GrepSearchTool()

    # Act
    result = tool.execute(pattern="token", path=str(tmp_path), output_mode="files")

    # Assert
    assert result.content["truncated"] is True
    assert len(result.content["files"]) == GREP_FILES_MAX_MATCHES
    assert result.content["num_matches"] == GREP_FILES_MAX_MATCHES + 3


def test_grep_skips_default_ignored_dirs(tmp_path):
    """忽略目录内的命中不计入结果。"""
    # Arrange
    _touch(tmp_path / "node_modules" / "pkg.js", "token\n")
    _touch(tmp_path / "src" / "app.js", "token\n")
    tool = GrepSearchTool()

    # Act
    result = tool.execute(pattern="token", path=str(tmp_path), output_mode="files")

    # Assert
    assert [os.path.basename(f) for f in result.content["files"]] == ["app.js"]


def test_grep_nonexistent_path_returns_error(tmp_path):
    """路径不存在 → success=False。"""
    # Act
    result = GrepSearchTool().execute(pattern="x", path=str(tmp_path / "void"))

    # Assert
    assert result.success is False
    assert "搜索路径不存在" in result.error


# ---------------------------------------------------------------------------
# FIX-3: grep ReDoS 缓解
# ---------------------------------------------------------------------------


def test_grep_skips_overlong_lines_and_counts_them(tmp_path):
    """超长行（>10 000 字符）不喂给正则：跳过并计入 skipped_long_lines。"""
    # Arrange: 一个超长行（含 needle，证明它确实被跳过而非匹配）+ 一个正常命中行
    long_line = "needle " + "x" * GREP_MAX_LINE_LENGTH
    _touch(tmp_path / "long.txt", long_line + "\nneedle here\n")
    tool = GrepSearchTool()

    # Act
    result = tool.execute(pattern="needle", path=str(tmp_path), output_mode="content")

    # Assert
    assert result.success is True
    assert result.content["num_matches"] == 1  # 只命中正常行
    assert result.content["matches"] == [f"{tmp_path / 'long.txt'}:2:needle here"]
    assert result.content["skipped_long_lines"] == 1


def test_grep_rejects_overlong_pattern(tmp_path):
    """超长正则（>1 000 字符）→ 干净错误（ReDoS 缓解）。"""
    # Arrange
    _touch(tmp_path / "a.txt", "data\n")

    # Act
    pattern = "a" * (GREP_MAX_PATTERN_LENGTH + 1)
    result = GrepSearchTool().execute(pattern=pattern, path=str(tmp_path))

    # Assert
    assert result.success is False
    assert "正则表达式过长" in result.error
    assert "ReDoS" in result.error


def test_grep_rejects_unknown_kwargs(tmp_path):
    """FIX-2 回归：拼错的参数名 → 干净错误。"""
    # Act —— 模拟 LLM 把 case_insensitive 拼成 ignore_case
    result = GrepSearchTool().execute(pattern="x", path=str(tmp_path), ignore_case=True)

    # Assert
    assert result.success is False
    assert "未知参数" in result.error
    assert "ignore_case" in result.error
