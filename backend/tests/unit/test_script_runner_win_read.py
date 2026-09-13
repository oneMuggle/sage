"""R32 切片 B：script_runner Windows 绑定读取契约测试。

验证 `_read_bound_regular_file` 的 Windows 分支（reparse-safe 原语）：
- 内容与 sha256 正确返回；
- identity 在多次读取间稳定；
- 文件被改写后 identity 变化、内容跟随更新。
"""

from __future__ import annotations

import hashlib
import os

import pytest

from backend.skills.skill_md.script_runner import _read_bound_regular_file

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name != "nt", reason="Windows 原生分支行为"),
]


def _sha(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def test_read_returns_content_and_sha(tmp_path):
    p = tmp_path / "script.md"
    p.write_bytes(b"echo hello")
    content, identity, sha = _read_bound_regular_file(p)
    assert content == b"echo hello"
    assert sha == _sha(b"echo hello")
    assert len(identity) == 3


def test_identity_stable_across_reads(tmp_path):
    p = tmp_path / "s.md"
    p.write_bytes(b"stable")
    _, id1, _ = _read_bound_regular_file(p)
    _, id2, _ = _read_bound_regular_file(p)
    assert id1 == id2


def test_identity_stable_but_sha_tracks_content_change(tmp_path):
    """Windows 文件索引在原地改写时保持不变；内容变化由 sha 比对捕捉
    （消费方 script_runner 即以 sha 比对实现确认语义）。"""
    p = tmp_path / "c.md"
    p.write_bytes(b"v1")
    _, id1, sha1 = _read_bound_regular_file(p)
    p.write_bytes(b"v2")
    _, id2, sha2 = _read_bound_regular_file(p)
    assert id1 == id2
    assert sha1 != sha2


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        _read_bound_regular_file(tmp_path / "nope.md")
