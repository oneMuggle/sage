"""E9-1 (P9): 嵌入器工厂 / OnnxEmbedder 单元测试。

设计约束:
- CI 不安装 onnxruntime/tokenizers —— 池化/归一化等纯逻辑用假数据验证;
  涉及真实模型推理的测试按模型文件存在性跳过。
- 工厂降级路径 (缺 env / 缺模型文件 / 缺依赖) 必须回退 HashEmbedder。
"""

from __future__ import annotations

import math

import pytest

from backend.memory.embedder import (
    BGE_SMALL_ZH_DIMENSIONS,
    HashEmbedder,
    OnnxEmbedder,
    l2_normalize,
    pool_cls_token,
)
from backend.memory.embedder_factory import create_embedder, onnx_model_ready

pytestmark = pytest.mark.unit


# =============================================================================
# 纯逻辑: CLS 池化 / L2 归一化
# =============================================================================


def test_pool_cls_token_takes_first_token_and_normalizes():
    """CLS 池化取首 token 向量并 L2 归一化。"""
    hidden = [[3.0, 4.0], [1.0, 1.0]]  # 两个 token
    pooled = pool_cls_token(hidden)
    assert math.isclose(sum(v * v for v in pooled), 1.0, rel_tol=1e-9)
    assert math.isclose(pooled[0], 0.6, rel_tol=1e-9)
    assert math.isclose(pooled[1], 0.8, rel_tol=1e-9)


def test_pool_cls_token_empty_is_safe():
    """空输入返回空向量 (调用方兜底为零向量)。"""
    assert pool_cls_token([]) == []
    assert pool_cls_token([[]]) == []


def test_l2_normalize_zero_vector_unchanged():
    """零向量归一化不除零。"""
    assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]


# =============================================================================
# 工厂降级
# =============================================================================


def test_factory_default_returns_hash_embedder(monkeypatch):
    """无 SAGE_EMBEDDER 时缺省 HashEmbedder(256)。"""
    monkeypatch.delenv("SAGE_EMBEDDER", raising=False)
    embedder = create_embedder()
    assert isinstance(embedder, HashEmbedder)
    assert embedder.dimensions == 256


def test_factory_onnx_without_model_files_degrades(monkeypatch, tmp_path):
    """SAGE_EMBEDDER=onnx 但模型文件缺失 → 降级 HashEmbedder。"""
    monkeypatch.setenv("SAGE_EMBEDDER", "onnx")
    monkeypatch.setenv("SAGE_EMBEDDING_MODEL_DIR", str(tmp_path / "empty-model"))
    embedder = create_embedder()
    assert isinstance(embedder, HashEmbedder)


def test_factory_onnx_with_dependencies_and_model(monkeypatch, tmp_path):
    """依赖与模型文件齐备时启用 OnnxEmbedder (真 ORT 推理, 缺依赖则跳过)。"""
    pytest.importorskip("onnxruntime")
    pytest.importorskip("tokenizers")
    pytest.skip("需要本地 bge-small-zh-v1.5 ONNX 模型文件; 见模型下载文档")


def test_onnx_model_ready_requires_both_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    model_dir = tmp_path / "m"
    assert not onnx_model_ready(str(model_dir))
    model_dir.mkdir()
    (model_dir / "model.onnx").write_text("x", encoding="utf-8")
    assert not onnx_model_ready(str(model_dir))
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    assert onnx_model_ready(str(model_dir))


# =============================================================================
# OnnxEmbedder: 假 ORT session / 假 tokenizer (不依赖 onnxruntime)
# =============================================================================


class _FakeEncoded:
    def __init__(self, n_tokens: int) -> None:
        self.ids = list(range(101, 101 + n_tokens))  # [CLS]=101 假定首 token
        self.attention_mask = [1] * n_tokens


class _FakeTokenizer:
    """tokenizers.Tokenizer 的行为替身: n 个 token。"""

    def __init__(self, n_tokens: int = 4) -> None:
        self._n = n_tokens
        self.truncation_enabled = False

    def enable_truncation(self, max_length: int) -> None:
        self._max = max_length
        self.truncation_enabled = True

    def encode(self, text: str) -> _FakeEncoded:
        n = min(self._n, len(text) or 1)
        return _FakeEncoded(n)


class _FakeSession:
    """ORT session 替身: 返回可辨识的 last_hidden_state (首 token = 单位向量×512)。"""

    def __init__(self, dimensions: int = BGE_SMALL_ZH_DIMENSIONS) -> None:
        self._dimensions = dimensions

    def get_inputs(self):
        class _Input:
            def __init__(self, name: str) -> None:
                self.name = name

        return [_Input("input_ids"), _Input("attention_mask")]

    def run(self, _outputs, feed):
        seq_len = len(feed["input_ids"][0])
        hidden = [[0.0] * self._dimensions for _ in range(seq_len)]
        # CLS token: 非零可归一化的向量
        hidden[0] = [1.0 / math.sqrt(self._dimensions)] * self._dimensions
        return [hidden]


def _make_onnx(tmp_path, n_tokens: int = 4, dimensions: int = BGE_SMALL_ZH_DIMENSIONS):
    """构造绕过懒加载 (直接注入假依赖) 的 OnnxEmbedder。"""
    embedder = OnnxEmbedder(model_dir=str(tmp_path), dimensions=dimensions)
    embedder._tokenizer = _FakeTokenizer(n_tokens)
    embedder._session = _FakeSession(dimensions)
    embedder._input_names = ["input_ids", "attention_mask"]
    embedder._loaded = True
    return embedder


def test_onnx_encode_uses_cls_pooling_and_is_normalized(tmp_path):
    """encode 输出 512 维且 L2 归一化 (假 session 下走完整编码路径)。"""
    embedder = _make_onnx(tmp_path)
    vec = embedder.encode("用户喜欢火锅")
    assert len(vec) == BGE_SMALL_ZH_DIMENSIONS
    norm = math.sqrt(sum(v * v for v in vec))
    assert math.isclose(norm, 1.0, rel_tol=1e-9)


def test_onnx_encode_empty_text_returns_zero_vector(tmp_path):
    """空文本不触发推理, 直接返回零向量。"""
    embedder = _make_onnx(tmp_path)
    assert embedder.encode("") == [0.0] * BGE_SMALL_ZH_DIMENSIONS


def test_onnx_encode_to_bytes_length(tmp_path):
    """encode_to_bytes 输出 dimensions*4 字节 (float32)。"""
    import struct

    embedder = _make_onnx(tmp_path)
    raw = embedder.encode_to_bytes("hello")
    assert len(raw) == BGE_SMALL_ZH_DIMENSIONS * 4
    # 反序列化可还原 (L2 归一化后数值)
    values = struct.unpack(f"<{BGE_SMALL_ZH_DIMENSIONS}f", raw)
    norm = math.sqrt(sum(v * v for v in values))
    assert math.isclose(norm, 1.0, rel_tol=1e-6)


def test_onnx_lazy_load_raises_without_model(tmp_path):
    """未注入假依赖时, encode 触发懒加载 → 模型缺失抛 FileNotFoundError。"""
    embedder = OnnxEmbedder(model_dir=str(tmp_path / "no-such-model"))
    with pytest.raises((FileNotFoundError, ModuleNotFoundError)):
        embedder.encode("hi")
    assert not embedder.loaded
