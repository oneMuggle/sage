"""file_tool 单元测试：ReadFileTool / WriteFileTool / ListDirTool

使用 pytest 内置的 tmp_path fixture 隔离文件系统副作用。
"""

import pytest

from backend.tools.file_tool import ListDirTool, ReadFileTool, WriteFileTool

pytestmark = pytest.mark.unit


# ---------- ReadFileTool ----------


def test_read_file_schema():
    """ReadFileTool schema 正确"""
    tool = ReadFileTool()
    schema = tool.schema
    assert schema.name == "read_file"
    assert "path" in schema.parameters["properties"]
    assert schema.parameters["required"] == ["path"]


def test_read_file_full_content(tmp_path):
    """读取存在的文件返回完整内容"""
    target = tmp_path / "hello.txt"
    target.write_text("line1\nline2\nline3", encoding="utf-8")

    tool = ReadFileTool()
    result = tool.execute(path=str(target))

    assert result.success is True
    assert result.content["total_lines"] == 3
    assert "line1" in result.content["content"]
    assert "line3" in result.content["content"]
    assert result.content["path"].endswith("hello.txt")


def test_read_file_with_offset_and_limit(tmp_path):
    """offset/limit 正确切片"""
    target = tmp_path / "many.txt"
    target.write_text("\n".join(f"row{i}" for i in range(1, 11)), encoding="utf-8")

    tool = ReadFileTool()
    result = tool.execute(path=str(target), offset=3, limit=2)

    assert result.success is True
    body = result.content["content"]
    # offset=3 → start=2, 即第 3 行(row3) 起，限 2 行 → row3, row4
    assert "row3" in body
    assert "row4" in body
    assert "row5" not in body


def test_read_file_missing(tmp_path):
    """文件不存在返回失败"""
    tool = ReadFileTool()
    result = tool.execute(path=str(tmp_path / "no_such.txt"))
    assert result.success is False
    assert "不存在" in result.error


def test_read_file_when_path_is_directory(tmp_path):
    """传入的是目录而非文件 → 失败"""
    tool = ReadFileTool()
    result = tool.execute(path=str(tmp_path))
    assert result.success is False
    assert "不是文件" in result.error


# ---------- WriteFileTool ----------


def test_write_file_schema():
    """WriteFileTool schema 正确"""
    tool = WriteFileTool()
    schema = tool.schema
    assert schema.name == "write_file"
    assert {"path", "content"}.issubset(schema.parameters["properties"].keys())
    assert schema.parameters["required"] == ["path", "content"]


def test_write_file_creates_new_file(tmp_path):
    """写入新文件返回 bytes_written"""
    target = tmp_path / "out.txt"
    tool = WriteFileTool()
    result = tool.execute(path=str(target), content="hello 世界")

    assert result.success is True
    assert target.read_text(encoding="utf-8") == "hello 世界"
    assert result.content["bytes_written"] == len("hello 世界".encode())
    assert result.content["mode"] == "w"


def test_write_file_creates_parent_dirs(tmp_path):
    """父目录不存在时自动创建"""
    target = tmp_path / "nested" / "deep" / "file.txt"
    tool = WriteFileTool()
    result = tool.execute(path=str(target), content="payload")

    assert result.success is True
    assert target.exists()
    assert target.read_text() == "payload"


def test_write_file_append_mode(tmp_path):
    """append=True 不覆盖"""
    target = tmp_path / "log.txt"
    target.write_text("first\n", encoding="utf-8")

    tool = WriteFileTool()
    result = tool.execute(path=str(target), content="second\n", append=True)

    assert result.success is True
    assert target.read_text() == "first\nsecond\n"
    assert result.content["mode"] == "a"


def test_write_file_failure_on_invalid_path():
    """无效路径（NUL 字符）触发异常分支"""
    tool = WriteFileTool()
    result = tool.execute(path="/tmp/invalid\0path", content="x")
    assert result.success is False
    assert result.error is not None


# ---------- ListDirTool ----------


def test_list_dir_schema():
    """ListDirTool schema"""
    tool = ListDirTool()
    schema = tool.schema
    assert schema.name == "list_dir"
    assert schema.parameters["required"] == ["path"]


def test_list_dir_sorts_dirs_first(tmp_path):
    """子目录排在文件之前，且按名称排序"""
    (tmp_path / "z_file.txt").write_text("a")
    (tmp_path / "a_file.txt").write_text("b")
    (tmp_path / "z_dir").mkdir()
    (tmp_path / "a_dir").mkdir()

    tool = ListDirTool()
    result = tool.execute(path=str(tmp_path))

    assert result.success is True
    items = result.content["items"]
    assert [it["name"] for it in items] == ["a_dir", "z_dir", "a_file.txt", "z_file.txt"]
    # file 有 size，dir 没有
    assert items[0]["type"] == "dir"
    assert items[0]["size"] is None
    assert items[2]["type"] == "file"
    assert items[2]["size"] == 1


def test_list_dir_hides_dotfiles_when_all_false(tmp_path):
    """all=False 隐藏 dotfile"""
    (tmp_path / ".hidden").write_text("h")
    (tmp_path / "visible.txt").write_text("v")

    tool = ListDirTool()
    result = tool.execute(path=str(tmp_path), all=False)

    assert result.success is True
    names = [it["name"] for it in result.content["items"]]
    assert "visible.txt" in names
    assert ".hidden" not in names


def test_list_dir_missing_path(tmp_path):
    """目录不存在 → 失败"""
    tool = ListDirTool()
    result = tool.execute(path=str(tmp_path / "no_such_dir"))
    assert result.success is False
    assert "不存在" in result.error


def test_list_dir_path_is_file(tmp_path):
    """路径是文件而非目录 → 失败"""
    target = tmp_path / "regular.txt"
    target.write_text("x")
    tool = ListDirTool()
    result = tool.execute(path=str(target))
    assert result.success is False
    assert "不是目录" in result.error


# ---------- _is_safe_path 帮助器 ----------


def test_read_file_is_safe_path_within_base(tmp_path):
    """_is_safe_path 对 base 内路径返回 True"""
    tool = ReadFileTool()
    inner = tmp_path / "sub" / "f.txt"
    inner.parent.mkdir(parents=True, exist_ok=True)
    inner.write_text("x")
    assert tool._is_safe_path(str(inner), str(tmp_path)) is True


def test_read_file_is_safe_path_outside_base(tmp_path):
    """_is_safe_path 对 base 外路径返回 False"""
    tool = ReadFileTool()
    # /etc 绝对不会在 tmp_path 下
    assert tool._is_safe_path("/etc/hosts", str(tmp_path)) is False


def test_read_file_is_safe_path_handles_exception():
    """传入非法路径 → 捕获异常返回 False"""
    tool = ReadFileTool()
    # 传入会触发 Path() 解析异常的输入（NUL 字符）
    assert tool._is_safe_path("/tmp/x\0y", "/tmp") is False
