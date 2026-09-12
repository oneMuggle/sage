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


# ---------- v2: 顶层定义边界分块 ----------


def test_semantic_chunks_align_to_defs():
    src = "\n".join(
        ["import os"]
        + [f"line{i}" for i in range(5)]
        + ["def alpha():", "    return 1"]
        + [""] + [f"pad{i}" for i in range(3)]
        + ["class Beta:", "    pass"]
        + ["", "tail"]
    )
    lines = src.splitlines()
    chunks = wi.chunk_file_semantic(lines, "py")

    starts = [start for start, _ in chunks]
    # alpha 与 Beta 的定义行各成一个 chunk（1-based 行号对齐）
    alpha_line = next(i + 1 for i, ln in enumerate(lines) if ln.startswith("def alpha"))
    beta_line = next(i + 1 for i, ln in enumerate(lines) if ln.startswith("class Beta"))
    assert alpha_line in starts
    assert beta_line in starts
    # 每个定义块 chunk 以定义（或装饰器）开头
    alpha_chunk = next(text for start, text in chunks if start == alpha_line)
    assert alpha_chunk.startswith("def alpha")


def test_semantic_decorator_attached_to_def():
    src = ["@staticmethod", "@cache", "def gamma():", "    return 2"]
    chunks = wi.chunk_file_semantic(src, "py")
    assert len(chunks) == 1
    start, text = chunks[0]
    assert start == 1
    assert text.startswith("@staticmethod")


def test_semantic_long_function_splits():
    body = ["def big():"] + [f"    x{i} = {i}" for i in range(120)]
    chunks = wi.chunk_file_semantic(body, "py")
    assert len(chunks) >= 2
    assert chunks[0][0] == 1
    # 覆盖到末尾（滑窗步进到收尾窗）
    assert chunks[-1][1].strip()


def test_semantic_fallback_without_defs():
    lines = [f"plain {i}" for i in range(90)]
    assert wi.chunk_file_semantic(lines, "py") == wi.chunk_file_lines(lines)


def test_semantic_dispatch_by_ext(tmp_path):
    py_file = tmp_path / "m.py"
    md_file = tmp_path / "n.md"
    py_lines = ["def a():", "    pass"]
    md_lines = [f"doc {i}" for i in range(50)]
    py_file.write_text("\n".join(py_lines), encoding="utf-8")
    md_file.write_text("\n".join(md_lines), encoding="utf-8")

    assert wi.chunk_file(py_file, py_lines) == [(1, "def a():\n    pass")]
    assert wi.chunk_file(md_file, md_lines) == wi.chunk_file_lines(md_lines)


def test_js_go_rs_boundaries():
    js = ["import x from 'y';", "export function foo() {", "  return 1", "}"]
    go = ["package m", "func Bar() {", "}"]
    rs = ["pub fn baz() {}", "struct S;"]
    assert wi.chunk_file_semantic(js, "js")[-1][1].startswith("export function foo")
    assert wi.chunk_file_semantic(go, "go")[-1][1].startswith("func Bar")
    assert len(wi.chunk_file_semantic(rs, "rs")) == 2


def test_chunker_version_rebuild(index_env, monkeypatch):
    config = {"base_url": "https://e.test", "api_key": "k", "model": "embed-1"}
    wi._index_workspace(str(index_env), config)

    # 篡改库内 chunker_version → 下次索引清库重建
    import sqlite3

    db_path = wi._index_dir(str(index_env)) / "index.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE meta SET value = '1' WHERE key = 'chunker_version'")
    conn.commit()
    conn.close()

    calls = {"n": 0}
    real = wi._embed_texts

    def counting(config, texts):
        calls["n"] += len(texts)
        return real(config, texts)

    monkeypatch.setattr(wi, "_embed_texts", counting)
    info = wi._index_workspace(str(index_env), config)
    assert info["indexed"] > 0  # 版本不符 → 文件被重建（而非增量跳过）


# ---------- v3: FTS5 关键词通道 + RRF 混合检索 ----------


def _fts_count(db_path, where=""):
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM chunks_fts{where}").fetchone()[0]
    finally:
        conn.close()


def test_fts_rows_synced_with_index_and_gone_files(index_env, tmp_path):
    config = {"base_url": "https://e.test", "api_key": "k", "model": "embed-1"}
    info = wi._index_workspace(str(index_env), config)
    db_path = wi._index_dir(str(index_env)) / "index.sqlite3"
    assert _fts_count(db_path) == info["chunks"]

    # 删除一个文件 → chunks 与 chunks_fts 同步清理
    (index_env / "README.md").unlink()
    wi._index_workspace(str(index_env), config)
    assert _fts_count(db_path) == _fts_count(db_path)  # 无异常即同步（详细计数走 chunks）
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        fts_n = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    finally:
        conn.close()
    assert chunks_n == fts_n


def test_hybrid_ranking_boosts_exact_identifier(index_env, monkeypatch):
    # 两个单块文件；向量全部退化为同一常量 → 向量路等分，顺序由插入序决定
    (index_env / "alpha_decoy.py").write_text("plain filler text here\n", encoding="utf-8")
    (index_env / "zeta_match.py").write_text("def zeta_token():\n    return 1\n", encoding="utf-8")

    def flat_embed(config, texts):
        # decoy/填充块与 query 同向（余弦 1.0，向量路霸榜）；
        # zeta 块与 query 仅有 0.2 的弱相似（向量路垫底但 > 0 不被过滤）
        out = []
        for text in texts:
            if text.startswith("def zeta_token"):
                out.append([0.2, 0.98] + [0.0] * 14)
            else:
                out.append([1.0] + [0.0] * 15)
        return out

    monkeypatch.setattr(wi, "_embed_texts", flat_embed)
    config = {"base_url": "https://e.test", "api_key": "k", "model": "embed-1"}
    wi._index_workspace(str(index_env), config)

    hits = wi._search_workspace(str(index_env), config, "zeta_token", limit=5)
    assert hits, "应有检索结果"
    # FTS 通道把精确标识符顶到第一（纯向量下它与 decoy 等分且排后）
    assert hits[0]["path"].endswith("zeta_match.py")


def test_fts_unavailable_falls_back_to_vector(index_env, monkeypatch):
    config = {"base_url": "https://e.test", "api_key": "k", "model": "embed-1"}
    wi._index_workspace(str(index_env), config)

    # 查询侧 FTS 不可用 → 降级纯向量，不抛异常
    monkeypatch.setattr(wi, "_ensure_fts", lambda conn: False)
    hits = wi._search_workspace(str(index_env), config, "login 逻辑", limit=5)
    assert isinstance(hits, list)
    assert hits


def test_fts_match_query_sanitized():
    q = wi._fts_match_query("def parse_config(file)!  空格")
    assert q is not None
    assert "parse_config" in q
    assert "!" not in q.replace('""', "")
    # CJK 连续串不被拆碎
    cjk = wi._fts_match_query("登录逻辑")
    assert '"登录逻辑"' in cjk
    # 全部为符号 → None
    assert wi._fts_match_query("!!! ***") is None


# ---------- 性能与可用性收尾（end_line / 并行嵌入 / 单批重试） ----------


def test_search_results_include_end_line(index_env):
    config = {"base_url": "https://e.test", "api_key": "k", "model": "embed-1"}
    wi._index_workspace(str(index_env), config)

    hits = wi._search_workspace(str(index_env), config, "login 逻辑", limit=5)
    assert hits and all("end_line" in h for h in hits)
    for h in hits:
        line_count = h["snippet"].count("\n") + 1
        # snippet 截断 400 字符不影响 end_line 计算（按完整 content 统计）
        assert h["end_line"] >= h["start_line"] + line_count - 1


def test_embed_texts_preserves_order_across_batches(tmp_path, monkeypatch):
    # 不用 index_env fixture —— 它会把 _embed_texts 替换成 fake，这里要测真函数
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "sage-data"))
    calls = []

    def slow_embed_batch(embed_config, batch, attempt=0):
        calls.append(len(batch))
        # 每批向量含批次长度，用于验证按原批序拼接
        return [[float(len(batch))] for _ in batch]

    monkeypatch.setattr(wi, "_embed_batch", slow_embed_batch)
    texts = [f"t{i}" for i in range(70)]  # 32 + 32 + 6 → 三批
    vectors = wi._embed_texts({"base_url": "u", "api_key": "k", "model": "m"}, texts)
    assert [v[0] for v in vectors] == [32.0] * 32 + [32.0] * 32 + [6.0] * 6
    assert calls == [32, 32, 6]


def test_embed_batch_retry_then_success(monkeypatch):
    attempts = {"n": 0}

    class FakeResponse:
        status_code = 200

        text = '{"data": [{"embedding": [1.0, 0.0]}, {"embedding": [1.0, 0.0]}]}'

        def raise_for_status(self):
            return None

    def flaky_http(url, json=None, headers=None, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("connection reset")
        return FakeResponse()

    monkeypatch.setattr("httpx.post", flaky_http)
    monkeypatch.setattr("time.sleep", lambda s: None)
    vectors = wi._embed_batch({"base_url": "u", "api_key": "k", "model": "m"}, ["a", "b"])
    assert vectors == [[1.0, 0.0], [1.0, 0.0]]
    assert attempts["n"] == 2
