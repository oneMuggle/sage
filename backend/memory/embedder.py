"""Embedder - 文本向量化接口

将文本转换为固定维度的浮点向量，供向量检索使用。

提供两种实现:
- HashEmbedder: 基于字符 n-gram 哈希，零依赖，适合快速启动
- ModelEmbedder: OpenAI 兼容 /embeddings API，真实语义相似度
    (对标 hermes-agent: wiki 子系统的 embedding 管线复用到记忆检索，
    环境变量约定一致 —— EMBED_BASE_URL / EMBED_API_KEY / EMBED_MODEL)
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
import threading
import time
from typing import List, Optional, Protocol


class EmbedderError(RuntimeError):
    """向量化失败（HTTP 错误 / 配置缺失 / 熔断打开）。

    调用方（VectorStore）捕获后降级：向量路缺席，关键词路兜底。
    """


class Embedder(Protocol):
    """Embedder 协议 — 将文本编码为浮点向量"""

    @property
    def dimensions(self) -> int:
        """向量维度"""
        ...

    def encode(self, text: str) -> List[float]:
        """将文本编码为固定维度的浮点向量"""
        ...

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码文本为向量列表（顺序与输入一致）"""
        ...

    def encode_to_bytes(self, text: str) -> bytes:
        """将文本编码为 sqlite-vec 兼容的 float32 little-endian bytes"""
        ...


class HashEmbedder:
    """基于字符 n-gram 哈希的轻量 Embedder

    原理:
    1. 提取文本中的所有字符 bigram 和 trigram
    2. 对每个 n-gram 做哈希，映射到 [0, dimensions) 的桶
    3. 桶内值累加，最后 L2 归一化

    优点:
    - 零外部依赖（不需要 numpy / sentence-transformers）
    - 中英文混合文本均可处理
    - 相似文本（共享 n-gram）得到相近向量

    缺点:
    - 无语义理解（"高兴" 和 "开心" 不会相近）
    - 未来可升级到 ModelEmbedder 获得真正的语义相似度
    """

    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def encode(self, text: str) -> List[float]:
        """将文本编码为固定维度的浮点向量

        Args:
            text: 输入文本

        Returns:
            长度为 dimensions 的浮点向量（L2 归一化）
        """
        if not text:
            return [0.0] * self._dimensions

        vector = [0.0] * self._dimensions

        # 提取 bigram 和 trigram
        ngrams: List[str] = []
        for n in (2, 3):
            for i in range(len(text) - n + 1):
                ngrams.append(text[i : i + n])

        if not ngrams:
            # 单字符文本：用字符本身作为 ngram
            ngrams = list(text)

        # 哈希映射到桶并累加
        for ng in ngrams:
            h = hashlib.md5(ng.encode("utf-8")).hexdigest()
            bucket = int(h[:8], 16) % self._dimensions
            # 用哈希的后续字节决定符号（+1 或 -1）
            sign = 1.0 if int(h[8:10], 16) % 2 == 0 else -1.0
            vector[bucket] += sign

        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码（HashEmbedder 无网络开销, 逐条编码即可）"""
        return [self.encode(t) for t in texts]

    def encode_to_bytes(self, text: str) -> bytes:
        """将文本编码为 sqlite-vec 兼容的 float32 little-endian bytes

        Args:
            text: 输入文本

        Returns:
            dimensions * 4 字节的 float32 little-endian 数据
        """
        vector = self.encode(text)
        return struct.pack(f"<{self._dimensions}f", *vector)


class ModelEmbedder:
    """基于 OpenAI 兼容 /embeddings API 的语义 Embedder

    对标 hermes-agent：记忆向量检索不应是假语义（HashEmbedder 的字符
    n-gram 哈希无法理解"高兴"≈"开心"）。wiki 子系统已有成熟的
    OpenAI 兼容 embedding 管线（backend/wiki/embeddings.py），本类把
    同样的端点约定复用到记忆检索。

    环境变量（与 wiki_routes 保持一致）:
    - EMBED_BASE_URL: embedding API 根地址（缺省回退 LLM_BASE_URL）
    - EMBED_API_KEY:  API key（缺省回退 LLM_API_KEY）
    - EMBED_MODEL:    模型名（默认 text-embedding-3-small）
    - SAGE_EMBED_DIM: 显式指定维度（可选；缺省从首个响应探测并缓存）
    - SAGE_EMBED_TIMEOUT_S: HTTP 超时秒数（默认 10）

    失败语义:
    - encode/encode_batch 失败抛 EmbedderError，由 VectorStore 捕获降级。
    - 连续失败 >= _CIRCUIT_THRESHOLD 次后熔断 _CIRCUIT_COOLDOWN_S 秒，
      熔断期间快速失败 —— 避免端点宕机时每次检索都吃满 HTTP 超时
      （test_event_loop_blocking 的 500ms 延迟门禁）。
    """

    _CIRCUIT_THRESHOLD = 3
    _CIRCUIT_COOLDOWN_S = 300.0
    # 单批上限：OpenAI 限制单请求 input 数组，超限分批
    _MAX_BATCH = 64

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "text-embedding-3-small",
        dimensions: Optional[int] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions  # None = 从首个响应探测
        self._timeout = timeout_seconds
        self._client = None  # 惰性 httpx.Client（线程内按需创建）
        self._dim_lock = threading.Lock()
        self._failures = 0
        self._circuit_open_until = 0.0

    @classmethod
    def from_env(cls) -> Optional[ModelEmbedder]:
        """从环境变量构造；未配置端点时返回 None。

        与 wiki_routes 的解析顺序一致：EMBED_* 优先，回退 LLM_*。
        """
        base_url = os.getenv("EMBED_BASE_URL") or os.getenv("LLM_BASE_URL")
        if not base_url:
            return None
        api_key = os.getenv("EMBED_API_KEY") or os.getenv("LLM_API_KEY") or ""
        model = os.getenv("EMBED_MODEL") or "text-embedding-3-small"
        dim_raw = os.getenv("SAGE_EMBED_DIM")
        dimensions = int(dim_raw) if dim_raw and dim_raw.isdigit() else None
        timeout_raw = os.getenv("SAGE_EMBED_TIMEOUT_S")
        try:
            timeout = float(timeout_raw) if timeout_raw else 10.0
        except ValueError:
            timeout = 10.0
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            dimensions=dimensions,
            timeout_seconds=timeout,
        )

    @property
    def dimensions(self) -> int:
        """向量维度。未探测到时返回 SAGE_EMBED_DIM 或模型缺省值。

        维度在首次成功编码后锁定；建表方（VectorStore）在维度变更时
        负责迁移重建。
        """
        if self._dimensions is not None:
            return self._dimensions
        return int(os.getenv("SAGE_EMBED_DIM") or 0) or 1536

    def _get_client(self):
        """惰性创建 httpx.Client（一次创建，跨调用复用连接池）"""
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def _check_circuit(self) -> None:
        """熔断打开期内快速失败"""
        if self._circuit_open_until > time.monotonic():
            raise EmbedderError(
                f"embedding 熔断中（连续失败 {self._failures} 次），"
                f"{int(self._circuit_open_until - time.monotonic())}s 后重试"
            )

    def _record_success(self) -> None:
        self._failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self, exc: Exception) -> None:
        self._failures += 1
        if self._failures >= self._CIRCUIT_THRESHOLD:
            self._circuit_open_until = time.monotonic() + self._CIRCUIT_COOLDOWN_S
            import logging

            logging.getLogger(__name__).warning(
                "ModelEmbedder 连续失败 %d 次，熔断 %ds: %s",
                self._failures,
                int(self._CIRCUIT_COOLDOWN_S),
                exc,
            )

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码文本为向量列表（自动分批，顺序与输入一致）

        Args:
            texts: 输入文本列表

        Returns:
            与输入等长的向量列表

        Raises:
            EmbedderError: HTTP 失败 / 响应非法 / 熔断打开
        """
        if not texts:
            return []
        self._check_circuit()

        url = f"{self._base_url}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        all_vectors: List[Optional[List[float]]] = [None] * len(texts)
        try:
            for start in range(0, len(texts), self._MAX_BATCH):
                batch = texts[start : start + self._MAX_BATCH]
                resp = self._get_client().post(
                    url,
                    headers=headers,
                    json={"model": self._model, "input": batch},
                )
                if resp.status_code != 200:
                    raise EmbedderError(
                        f"embedding API HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                data = resp.json().get("data", [])
                if len(data) != len(batch):
                    raise EmbedderError(
                        f"embedding API 返回 {len(data)} 条, 期望 {len(batch)}"
                    )
                # OpenAI 兼容响应保证 data[i].index 对应输入下标；防御性排序
                items = sorted(data, key=lambda d: d.get("index", 0))
                for offset, item in enumerate(items):
                    vector = item.get("embedding")
                    if not vector:
                        raise EmbedderError("embedding API 返回空向量")
                    if self._dimensions is None:
                        with self._dim_lock:
                            if self._dimensions is None:
                                self._dimensions = len(vector)
                    all_vectors[start + offset] = vector
        except EmbedderError:
            self._record_failure(EmbedderError("encode_batch 失败"))
            raise
        except Exception as exc:  # noqa: BLE001 — 网络/解析错误统一降级
            self._record_failure(exc)
            raise EmbedderError(f"embedding 请求失败: {exc}") from exc

        self._record_success()
        if any(v is None for v in all_vectors):  # 防御：不应发生（缺失即抛错）
            raise EmbedderError("embedding 响应缺失部分向量")
        return [v for v in all_vectors if v is not None]

    def encode(self, text: str) -> List[float]:
        """将文本编码为固定维度的浮点向量

        Args:
            text: 输入文本

        Returns:
            长度为 dimensions 的浮点向量

        Raises:
            EmbedderError: HTTP 失败 / 熔断打开 / 空文本
        """
        if not text:
            return [0.0] * self.dimensions
        return self.encode_batch([text])[0]

    def encode_to_bytes(self, text: str) -> bytes:
        """将文本编码为 sqlite-vec 兼容的 float32 little-endian bytes"""
        vector = self.encode(text)
        return struct.pack(f"<{len(vector)}f", *vector)


def create_embedder() -> Embedder:
    """按配置创建 Embedder（ModelEmbedder 优先，HashEmbedder 兜底）

    选择逻辑（对标 hermes 的可插拔 memory provider 思路，保持零配置可用）:
    - SAGE_EMBEDDER=model  强制 ModelEmbedder（端点未配置时告警并回退 hash）
    - SAGE_EMBEDDER=hash   强制 HashEmbedder
    - 未设置: EMBED_MODEL 或 EMBED_BASE_URL/LLM_BASE_URL 已配置 → model
    """
    import logging

    logger = logging.getLogger(__name__)
    choice = (os.getenv("SAGE_EMBEDDER") or "").strip().lower()
    if choice == "hash":
        return HashEmbedder(dimensions=256)
    embedder = ModelEmbedder.from_env()
    if embedder is not None:
        logger.info(
            "记忆检索使用语义 Embedder: model=%s base_url=%s",
            embedder._model,
            embedder._base_url,
        )
        return embedder
    if choice == "model":
        logger.warning(
            "SAGE_EMBEDDER=model 但未配置 EMBED_BASE_URL/EMBED_MODEL，回退 HashEmbedder"
        )
    return HashEmbedder(dimensions=256)
