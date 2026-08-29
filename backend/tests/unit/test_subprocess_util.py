"""subprocess_util 共享子进程原语单元测试。"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from unittest import mock

import pytest

from backend.tools import subprocess_util
from backend.tools.subprocess_util import (
    MAX_OUTPUT_CAP_BYTES,
    MAX_OUTPUT_OFFSET_BYTES,
    kill_process_tree,
    make_temp_output_file,
    read_capped_output,
    unlink_owned,
    unlink_quietly,
)

pytestmark = pytest.mark.unit


def test_make_temp_output_file_creates_empty_readable_file():
    """建出的文件存在且为空。"""
    # Arrange / Act
    path = make_temp_output_file()

    # Assert
    try:
        assert os.path.exists(path)
        with open(path, "rb") as handle:
            assert handle.read() == b""
    finally:
        unlink_quietly(path)


def test_read_capped_output_returns_full_text_under_cap():
    """内容小于上限 → 完整返回, 未截断, 偏移等于字节数。"""
    # Arrange
    path = make_temp_output_file()
    with open(path, "wb") as handle:
        handle.write(b"hello world")

    # Act
    try:
        text, truncated, offset = read_capped_output(path, cap=1024)
    finally:
        unlink_quietly(path)

    # Assert
    assert text == "hello world"
    assert truncated is False
    assert offset == 11


def test_read_capped_output_truncates_beyond_cap():
    """内容超上限 → 截断标记 + 文本长度不超上限余量。"""
    # Arrange
    path = make_temp_output_file()
    with open(path, "wb") as handle:
        handle.write(b"y" * 5000)

    # Act
    try:
        text, truncated, offset = read_capped_output(path, cap=100)
    finally:
        unlink_quietly(path)

    # Assert
    assert truncated is True
    assert "已截断" in text
    assert offset == 100


def test_read_capped_output_honors_offset_for_incremental_reads():
    """从 offset 起读 → 只拿新增部分（后台增量读的核心语义）。"""
    # Arrange
    path = make_temp_output_file()
    with open(path, "wb") as handle:
        handle.write(b"first")

    # Act
    try:
        text1, _, offset1 = read_capped_output(path, cap=1024)
        with open(path, "ab") as handle:
            handle.write(b"second")
        text2, _, offset2 = read_capped_output(path, cap=1024, offset=offset1)
    finally:
        unlink_quietly(path)

    # Assert
    assert text1 == "first"
    assert text2 == "second"
    assert offset2 == 11


def test_read_capped_output_missing_file_returns_error_text_not_raise():
    """文件不存在 → 返回错误说明文本, 不抛异常（清理路径不允许崩）。"""
    text, truncated, offset = read_capped_output("/nonexistent/path/xyz", cap=1024)

    assert "读取子进程输出失败" in text
    assert truncated is False
    assert offset == 0


def test_read_capped_output_rejects_symlink_without_reading_target(tmp_path):
    """输出路径为符号链接时不得读取链接目标。"""
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("平台不支持 O_NOFOLLOW")
    target = tmp_path / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "output.out"
    link.symlink_to(target)

    text, truncated, offset = read_capped_output(str(link), cap=1024)

    assert "读取子进程输出失败" in text
    assert "secret" not in text
    assert truncated is False
    assert offset == 0


def test_read_capped_output_rejects_path_replaced_after_lstat(tmp_path, monkeypatch):
    """lstat 与 open 之间替换输出路径时不得读取新目标。"""
    output = tmp_path / "output.out"
    output.write_text("old", encoding="utf-8")
    target = tmp_path / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    original_open = os.open
    replaced = False

    def replace_before_open(path, flags, *args):
        nonlocal replaced
        if path == str(output) and not replaced:
            replaced = True
            output.unlink()
            output.symlink_to(target)
        return original_open(path, flags, *args)

    monkeypatch.setattr("backend.tools.subprocess_util.os.open", replace_before_open)
    text, truncated, offset = read_capped_output(str(output), cap=1024)

    assert replaced is True
    assert "读取子进程输出失败" in text
    assert "secret" not in text
    assert truncated is False
    assert offset == 0


def test_read_capped_output_rejects_non_regular_file(tmp_path):
    """目录等非普通文件不能作为输出读取。"""
    directory = tmp_path / "output.out"
    directory.mkdir()

    text, truncated, offset = read_capped_output(str(directory), cap=1024)

    assert "不是普通文件" in text
    assert truncated is False
    assert offset == 0


def test_read_capped_output_closes_fd_when_fstat_fails(tmp_path, monkeypatch):
    """打开后 fstat 失败时必须关闭已取得的 descriptor。"""
    output = tmp_path / "output.out"
    output.write_bytes(b"data")
    original_open = os.open
    original_close = os.close
    opened_fds = []
    closed_fds = []

    def open_and_record(path, flags, *args):
        fd = original_open(path, flags, *args)
        opened_fds.append(fd)
        return fd

    def fail_fstat(_fd):
        raise OSError("fstat failed")

    def close_and_record(fd):
        closed_fds.append(fd)
        return original_close(fd)

    monkeypatch.setattr("backend.tools.subprocess_util.os.open", open_and_record)
    monkeypatch.setattr("backend.tools.subprocess_util.os.fstat", fail_fstat)
    monkeypatch.setattr("backend.tools.subprocess_util.os.close", close_and_record)

    text, truncated, offset = read_capped_output(str(output), cap=1024)

    assert "读取子进程输出失败" in text
    assert truncated is False
    assert offset == 0
    assert opened_fds
    assert closed_fds == opened_fds


@pytest.mark.parametrize(
    ("cap", "offset"),
    [(-1, 0), (0, -1)],
)
def test_read_capped_output_rejects_negative_limits(cap, offset):
    """读取边界不得为负数。"""
    with pytest.raises(ValueError, match="non-negative"):
        read_capped_output("/unused", cap=cap, offset=offset)


def test_read_capped_output_rejects_cap_above_shared_maximum():
    """读取上限必须受共享最大值约束。"""
    with pytest.raises(ValueError, match="maximum"):
        read_capped_output("/unused", cap=MAX_OUTPUT_CAP_BYTES + 1)


def test_read_capped_output_rejects_offset_above_shared_maximum():
    """offset 超出共享最大值时, 在打开文件前明确拒绝。"""
    with pytest.raises(ValueError, match="offset exceeds maximum"):
        read_capped_output(
            "/unused", cap=0, offset=MAX_OUTPUT_OFFSET_BYTES + 1
        )


def test_read_capped_output_rejects_extremely_large_offset():
    """极大 Python 整数不能穿透到文件 seek。"""
    with pytest.raises(ValueError, match="offset exceeds maximum"):
        read_capped_output("/unused", cap=0, offset=10**100)


@pytest.mark.parametrize(
    ("parameter", "value"),
    [("cap", True), ("cap", False), ("offset", True), ("offset", False)],
)
def test_read_capped_output_rejects_bool_limits(parameter, value):
    """bool 虽是 int 子类, 但不是合法边界参数。"""
    kwargs = {"cap": 0, **{parameter: value}}
    with pytest.raises(ValueError, match="integer"):
        read_capped_output("/unused", **kwargs)


def test_kill_process_tree_exited_leader_does_not_kill_group_by_default():
    process = mock.Mock(pid=123)
    process.poll.return_value = 0

    with mock.patch("backend.tools.subprocess_util.os.killpg") as killpg:
        assert kill_process_tree(process, reap=False, process_group_id=123) is True

    killpg.assert_not_called()


def test_kill_process_tree_allows_observed_unreaped_exit_group_kill():
    process = mock.Mock(pid=123)

    with mock.patch("backend.tools.subprocess_util.os.killpg") as killpg:
        assert kill_process_tree(
            process,
            reap=False,
            process_group_id=123,
            kill_exited_group=True,
            leader_exit_observed=True,
        ) is True

    killpg.assert_called_once_with(123, signal.SIGKILL)


def test_kill_process_tree_rejects_non_independent_process_group():
    """POSIX: 非独立进程组不得误杀整个后端进程组。"""
    if os.name == "nt":
        pytest.skip("进程组语义仅在 POSIX 验证")
    process = mock.Mock(pid=123)
    with mock.patch("backend.tools.subprocess_util.os.killpg") as killpg:
        result = kill_process_tree(process, reap=False, process_group_id=456)

    assert result is False
    killpg.assert_not_called()
    process.kill.assert_not_called()


def test_kill_process_tree_kills_grandchild_on_posix(tmp_path):
    """POSIX: 杀进程组连孙进程一起收（孙进程不留下 marker 文件）。"""
    # Arrange
    if os.name == "nt":
        pytest.skip("进程组语义仅在 POSIX 验证")
    marker = tmp_path / "orphan.txt"
    grandchild_started = tmp_path / "grandchild-ready.txt"
    child_started = tmp_path / "child-ready.txt"
    grandchild_code = (
        "import time; "
        f"open({str(grandchild_started)!r}, 'w').close(); "
        "time.sleep(3); "
        f"open({str(marker)!r}, 'w').write('orphan')"
    )
    child_code = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild_code!r}])\n"
        f"open({str(child_started)!r}, 'w').close()\n"
        "time.sleep(5)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    process_group_id = os.getpgid(process.pid)
    assert process_group_id == process.pid
    deadline = time.monotonic() + 5
    while not child_started.exists() or not grandchild_started.exists():
        if time.monotonic() >= deadline:
            process.kill()
            process.wait()
            pytest.fail("child/grandchild 未在超时前启动")
        time.sleep(0.01)

    # Act
    kill_process_tree(process, reap=True, process_group_id=process_group_id)

    # Assert
    time.sleep(4)
    assert not marker.exists(), "孙进程存活并写了 marker → 进程组未被完整终止"


def test_start_collectors_rolls_back_all_collectors_when_second_start_fails(monkeypatch):
    """第二个 collector 启动失败时，已构造的两个 collector 都要回滚。"""
    instances = []

    class FakeCollector:
        def __init__(self, stream, path, max_bytes):
            self.stream = stream
            self.path = path
            self.max_bytes = max_bytes
            self.stop_calls = []
            instances.append(self)

        def start(self):
            if len(instances) == 2:
                raise RuntimeError("second collector failed")

        def stop(self, timeout=None):
            self.stop_calls.append(timeout)
            return True

        def abort(self, timeout=None):
            self.stop_calls.append(("abort", timeout))
            return True

        def close(self):
            self.stop_calls.append("close")

    monkeypatch.setattr(subprocess_util, "BoundedOutputCollector", FakeCollector)

    with pytest.raises(RuntimeError, match="second collector failed"):
        subprocess_util.start_bounded_output_collectors(
            mock.Mock(), mock.Mock(), "/tmp/stdout.out", "/tmp/stderr.out", max_bytes=1024
        )

    assert len(instances) == 2
    assert instances[0].stop_calls == [("abort", 0.5)]
    assert instances[1].stop_calls == [("abort", 0.5)]


def test_unlink_owned_missing_path_is_idempotent_success(tmp_path):
    path = tmp_path / "output.out"
    path.touch()
    identity = subprocess_util.file_identity(str(path))
    path.unlink()

    assert unlink_owned(str(path), identity) is True


def test_unlink_owned_identity_mismatch_does_not_remove_replacement(tmp_path):
    path = tmp_path / "output.out"
    replacement = tmp_path / "replacement.out"
    path.write_bytes(b"old")
    identity = subprocess_util.file_identity(str(path))
    replacement.write_bytes(b"new")
    path.unlink()
    replacement.rename(path)

    assert unlink_owned(str(path), identity) is False
    assert path.exists()
