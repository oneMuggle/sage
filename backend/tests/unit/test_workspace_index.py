# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""F2 (round5 批次 E): 工作区语义索引纯逻辑测试。

embedding 经 monkeypatch 注入假向量（哈希驱动的确定性向量），不发网络。
"""

from __future__ import annotations

import hashlib

import pytest

from backend.tools import workspace_index as wi

pytestmark = pytest.mark.unit


def _fake_embed(config, texts):
    """确定性假向量：文本 sha1 派生 16 维（相似文本相近性不保证,仅测链路）。"""
    out = []
    for text in texts:
        digest = hashlib.sha1(text.encode("utf-8")).digest()[:16]
        out.append([b / 255.0 for b in digest])
    return out


@pytest.fixture()
def index_env(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "app.py").write_text(
        "def login():\n    return True\n" * 30, encoding="utf-8"
    )
    (workspace / "README.md").write_text("# 项目\n\n说明文档\n", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "junk.js").write_text("var x=1;\n" * 50, encoding="utf-8")
    monkeypatch.setattr(wi, "_embed_texts", _fake_embed)
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "sage-data"))
    return workspace


def test_chunks_slide_with_overlap():
    lines = [f"line{i}" for i in range(100)]
    chunks = wi.chunk_file_lines(lines, chunk_lines=40)
    # 100 行 40 窗口 30 步进 → 覆盖到末尾
    assert chunks[0][0] == 1
    assert chunks[-1][0] <= 100
    assert all(text for _, text in chunks)


def test_iter_source_files_prunes_excluded(index_env):
    files = wi._iter_source_files(str(index_env))
    names = [f.name for f in files]
    assert "app.py" in names
    assert "README.md" in names
    assert "junk.js" not in names  # node_modules 被剪枝


def test_index_and_search_roundtrip(index_env):
    config = {"base_url": "https://e.test", "api_key": "k", "model": "embed-1"}
    info = wi._index_workspace(str(index_env), config)
    assert info["indexed"] == 2
    assert info["chunks"] > 0

    hits = wi._search_workspace(str(index_env), config, "login 逻辑", limit=5)
    assert isinstance(hits, list)
    # 余弦检索应命中 app.py（唯一含 login 文本的块）
    assert any(h["path"].endswith("app.py") for h in hits)


def test_incremental_index_skips_unchanged(index_env):
    config = {"base_url": "https://e.test", "api_key": "k", "model": "embed-1"}
    wi._index_workspace(str(index_env), config)
    info = wi._index_workspace(str(index_env), config)
    assert info["indexed"] == 0  # mtime/size 未变 → 零重嵌

    # 改动文件 → 该文件重嵌
    (index_env / "app.py").write_text("def logout():\n    return False\n" * 30, encoding="utf-8")
    info = wi._index_workspace(str(index_env), config)
    assert info["indexed"] == 1


def test_dim_change_rebuilds(index_env, monkeypatch):
    config = {"base_url": "https://e.test", "api_key": "k", "model": "embed-1"}
    wi._index_workspace(str(index_env), config)

    # 换维度（假向量长度变化）→ 清库重建
    def dim8_embed(config, texts):
        out = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()[:8]
            out.append([b / 255.0 for b in digest])
        return out

    monkeypatch.setattr(wi, "_embed_texts", dim8_embed)
    info = wi._index_workspace(str(index_env), config)
    assert info["dim"] == 8
    assert info["chunks"] > 0  # 重建后仍有内容


def test_stats_before_index(index_env):
    stats = wi.workspace_index_stats(str(index_env))
    assert stats == {"indexed_files": 0, "chunks": 0}
