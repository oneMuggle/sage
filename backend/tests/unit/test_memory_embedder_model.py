"""ModelEmbedder 与 create_embedder 工厂测试

覆盖:
- from_env / create_embedder 的配置解析（EMBED_* / LLM_* / SAGE_EMBEDDER）
- encode / encode_batch / encode_to_bytes（mock httpx 响应）
- 维度探测与锁定
- HTTP 失败 → EmbedderError + 连续失败熔断
- HashEmbedder 回归（zero-vector / bytes 长度）
"""

from __future__ import annotations

import struct
from unittest.mock import MagicMock

import pytest

from backend.memory.embedder import (
    EmbedderError,
    HashEmbedder,
    ModelEmbedder,
    create_embedder,
)

pytestmark = pytest.mark.unit


def _fake_response(vectors):
    """构造 OpenAI 兼容 /embeddings 响应的 mock"""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    }
    return resp


def _patch_client(monkeypatch, embedder, post_side_effect=None, post_return=None):
    """把 embedder 的 httpx.Client 换成 mock"""
    client = MagicMock()
    if post_side_effect is not None:
        client.post.side_effect = post_side_effect
    else:
        client.post.return_value = post_return
    monkeypatch.setattr(embedder, "_get_client", lambda: client)
    return client


class TestModelEmbedderFromEnv:
    def test_from_env_none_without_endpoint(self, monkeypatch):
        for var in (
            "EMBED_BASE_URL",
            "LLM_BASE_URL",
            "EMBED_API_KEY",
            "LLM_API_KEY",
            "EMBED_MODEL",
            "SAGE_EMBEDDER",
            "SAGE_EMBED_DIM",
        ):
            monkeypatch.delenv(var, raising=False)
        assert ModelEmbedder.from_env() is None

    def test_from_env_with_embed_vars(self, monkeypatch):
        monkeypatch.setenv("EMBED_BASE_URL", "http://mock:9999/v1")
        monkeypatch.setenv("EMBED_API_KEY", "sk-test")
        monkeypatch.setenv("EMBED_MODEL", "mock-embed")
        embedder = ModelEmbedder.from_env()
        assert embedder is not None
        assert embedder._base_url == "http://mock:9999/v1"
        assert embedder._model == "mock-embed"

    def test_from_env_falls_back_to_llm_vars(self, monkeypatch):
        monkeypatch.delenv("EMBED_BASE_URL", raising=False)
        monkeypatch.delenv("EMBED_API_KEY", raising=False)
        monkeypatch.setenv("LLM_BASE_URL", "http://llm-mock:1/v1")
        monkeypatch.setenv("LLM_API_KEY", "sk-llm")
        embedder = ModelEmbedder.from_env()
        assert embedder is not None
        assert embedder._api_key == "sk-llm"


class TestCreateEmbedder:
    def test_force_hash(self, monkeypatch):
        monkeypatch.setenv("SAGE_EMBEDDER", "hash")
        monkeypatch.setenv("EMBED_BASE_URL", "http://mock:9999/v1")
        assert isinstance(create_embedder(), HashEmbedder)

    def test_model_when_endpoint_configured(self, monkeypatch):
        monkeypatch.delenv("SAGE_EMBEDDER", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.setenv("EMBED_BASE_URL", "http://mock:9999/v1")
        monkeypatch.setenv("EMBED_MODEL", "mock-embed")
        embedder = create_embedder()
        assert isinstance(embedder, ModelEmbedder)

    def test_hash_fallback_when_unconfigured(self, monkeypatch):
        for var in ("SAGE_EMBEDDER", "EMBED_BASE_URL", "LLM_BASE_URL", "EMBED_MODEL"):
            monkeypatch.delenv(var, raising=False)
        embedder = create_embedder()
        assert isinstance(embedder, HashEmbedder)
        assert embedder.dimensions == 256

    def test_model_requested_but_unconfigured_falls_back(self, monkeypatch):
        monkeypatch.setenv("SAGE_EMBEDDER", "model")
        monkeypatch.delenv("EMBED_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        assert isinstance(create_embedder(), HashEmbedder)


class TestModelEmbedderEncode:
    def _make(self, monkeypatch, **kwargs):
        monkeypatch.delenv("SAGE_EMBED_DIM", raising=False)
        return ModelEmbedder(
            base_url="http://mock:9999/v1",
            api_key="sk-test",
            model="mock-embed",
            **kwargs,
        )

    def test_encode_returns_vector_and_detects_dim(self, monkeypatch):
        embedder = self._make(monkeypatch)
        vec = [0.1] * 8
        _patch_client(monkeypatch, embedder, post_return=_fake_response([vec]))
        result = embedder.encode("你好")
        assert result == vec
        assert embedder.dimensions == 8

    def test_encode_empty_text_zero_vector(self, monkeypatch):
        embedder = self._make(monkeypatch, dimensions=16)
        assert embedder.encode("") == [0.0] * 16

    def test_encode_batch_preserves_order_across_batches(self, monkeypatch):
        embedder = self._make(monkeypatch)
        embedder._MAX_BATCH = 2
        texts = ["a", "b", "c", "d", "e"]
        expected = [[float(i)] * 4 for i in range(5)]

        seen_batches = []
        offset = 0

        def post_side_effect(url, headers=None, json=None):
            nonlocal offset
            seen_batches.append(json["input"])
            batch_vectors = [expected[offset + i] for i in range(len(json["input"]))]
            offset += len(json["input"])
            return _fake_response(batch_vectors)

        _patch_client(monkeypatch, embedder, post_side_effect=post_side_effect)
        result = embedder.encode_batch(texts)
        assert result == expected
        assert seen_batches == [["a", "b"], ["c", "d"], ["e"]]

    def test_encode_to_bytes_float32_len(self, monkeypatch):
        embedder = self._make(monkeypatch)
        vec = [0.5] * 6
        _patch_client(monkeypatch, embedder, post_return=_fake_response([vec]))
        raw = embedder.encode_to_bytes("text")
        assert len(raw) == 6 * 4
        assert struct.unpack("<6f", raw) == tuple(vec)

    def test_http_error_raises_embedder_error(self, monkeypatch):
        embedder = self._make(monkeypatch)
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "boom"
        _patch_client(monkeypatch, embedder, post_return=resp)
        with pytest.raises(EmbedderError):
            embedder.encode("text")

    def test_mismatched_batch_len_raises(self, monkeypatch):
        embedder = self._make(monkeypatch)
        _patch_client(
            monkeypatch,
            embedder,
            post_return=_fake_response([[0.1] * 4]),  # 请求 2 条只回 1 条
        )
        with pytest.raises(EmbedderError):
            embedder.encode_batch(["a", "b"])

    def test_circuit_opens_after_consecutive_failures(self, monkeypatch):
        embedder = self._make(monkeypatch)
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "boom"
        client = _patch_client(monkeypatch, embedder, post_return=resp)

        for _ in range(ModelEmbedder._CIRCUIT_THRESHOLD):
            with pytest.raises(EmbedderError):
                embedder.encode("text")

        # 熔断打开: 不再发起 HTTP 请求即快速失败
        calls_after_burnout = client.post.call_count
        with pytest.raises(EmbedderError):
            embedder.encode("text")
        assert client.post.call_count == calls_after_burnout

    def test_success_resets_failure_counter(self, monkeypatch):
        embedder = self._make(monkeypatch)
        bad = MagicMock()
        bad.status_code = 500
        bad.text = "boom"
        client = MagicMock()
        client.post.side_effect = [bad, bad, _fake_response([[0.1] * 4])]
        monkeypatch.setattr(embedder, "_get_client", lambda: client)

        with pytest.raises(EmbedderError):
            embedder.encode("a")
        with pytest.raises(EmbedderError):
            embedder.encode("b")
        assert embedder.encode("c") == [0.1] * 4
        assert embedder._failures == 0
        # 之后再次失败需要重新累计, 不会立即熔断
        client.post.side_effect = [bad, bad, bad]
        for _ in range(ModelEmbedder._CIRCUIT_THRESHOLD):
            with pytest.raises(EmbedderError):
                embedder.encode("d")


class TestHashEmbedderRegression:
    def test_zero_vector_for_empty(self):
        emb = HashEmbedder(dimensions=32)
        assert emb.encode("") == [0.0] * 32

    def test_bytes_length(self):
        emb = HashEmbedder(dimensions=64)
        assert len(emb.encode_to_bytes("text")) == 64 * 4
