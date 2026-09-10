"""pandoc .doc → .docx 适配器测试。

- convert_docx_passthrough: .docx 直接返回，不调 pandoc
- convert_doc_to_docx_uses_cache: 同 sha256 第二次命中缓存（pandoc 不可用时 skip）
- convert_nonexistent_raises: 不存在的文件 → JournalPandocError
"""
import shutil
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.office.journal.errors import JournalPandocError
from backend.office.journal.pandoc_adapter import (
    cache_key_for,
    convert_doc_to_docx,
    is_pandoc_available,
)


def test_is_pandoc_available_returns_bool():
    assert isinstance(is_pandoc_available(), bool)


def test_cache_key_for_is_sha256_hex():
    p = Path(__file__)
    key = cache_key_for(p)
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


def test_convert_docx_passthrough(tmp_path: Path):
    """传入 .docx 应直接返回原文件 path（不调 pandoc）。"""
    src = tmp_path / "in.docx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("word/document.xml", "<w:document xmlns:w='w'/>")
        z.writestr("[Content_Types].xml", "<?xml version='1.0' encoding='UTF-8'?>")
    out = convert_doc_to_docx(src, cache_dir=tmp_path / "cache")
    assert out == src
    assert (tmp_path / "cache").exists() is False  # passthrough 不写缓存


@pytest.mark.skipif(
    shutil.which("pandoc") is None, reason="pandoc 系统依赖未安装"
)
def test_convert_doc_to_docx_uses_cache(tmp_path: Path, monkeypatch):
    """同 sha256 第二次调用应命中缓存（不调 pandoc 子进程）。

    用 monkeypatch 模拟 pandoc 子进程：第一次写出一个合法 docx 到 tmp_out，
    第二次因为缓存命中 → 直接返回缓存路径，subprocess.run 不被调用。
    """
    # 构造一个伪 .doc 文件（CFBF/OLE2 头 + 任意 payload）
    src = tmp_path / "in.doc"
    src.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 4096)
    cache = tmp_path / "cache"

    call_count = {"n": 0}

    def fake_run(argv, **kwargs):  # noqa: ARG001
        call_count["n"] += 1
        # 模拟 pandoc 写入 tmp_out 路径
        tmp_out = Path(argv[argv.index("--output") + 1])
        tmp_out.parent.mkdir(parents=True, exist_ok=True)
        # 写一个最小合法 docx（zip + Content_Types）
        with zipfile.ZipFile(tmp_out, "w") as z:
            z.writestr("[Content_Types].xml", "<?xml version='1.0'?>")
            z.writestr("word/document.xml", "<w:document/>")
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out1 = convert_doc_to_docx(src, cache_dir=cache)
    out2 = convert_doc_to_docx(src, cache_dir=cache)
    # 缓存命中 → 第二次的输出路径与第一次一致（绝对路径相等）
    assert out1 == out2
    # subprocess.run 只调用了一次（第二次命中缓存）
    assert call_count["n"] == 1
    # 缓存文件存在
    cached = list(cache.glob("*.docx"))
    assert len(cached) == 1


def test_convert_nonexistent_raises(tmp_path: Path):
    with pytest.raises(JournalPandocError):
        convert_doc_to_docx(tmp_path / "ghost.doc", cache_dir=tmp_path / "cache")
