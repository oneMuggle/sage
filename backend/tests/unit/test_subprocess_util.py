"""subprocess_util 共享子进程原语单元测试。"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from backend.tools.subprocess_util import (
    kill_process_tree,
    make_temp_output_file,
    read_capped_output,
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
    # Arrange / Act
    text, truncated, offset = read_capped_output("/nonexistent/path/xyz", cap=1024)

    # Assert
    assert "读取子进程输出失败" in text
    assert truncated is False
    assert offset == 0


def test_kill_process_tree_kills_grandchild_on_posix(tmp_path):
    """POSIX: 杀进程组连孙进程一起收（孙进程不留下 marker 文件）。"""
    # Arrange
    if os.name == "nt":
        pytest.skip("进程组语义仅在 POSIX 验证")
    marker = tmp_path / "orphan.txt"
    child_code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', "
        f"\"import time; time.sleep(3); open({str(marker)!r}, 'w').write('orphan')\"]\n"
        "time.sleep(5)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.5)

    # Act
    kill_process_tree(process)

    # Assert
    time.sleep(4)
    assert not marker.exists(), "孙进程存活并写了 marker → 进程组未被完整终止"


def test_unlink_quietly_on_missing_path_does_not_raise():
    """删不存在的文件静默返回。"""
    # Arrange / Act / Assert — 不抛即通过
    unlink_quietly("/nonexistent/path/xyz")
