"""Embedder - 文本向量化接口

将文本转换为固定维度的浮点向量，供向量检索使用。

提供三种实现:
- HashEmbedder: 基于字符 n-gram 哈希，零依赖，适合快速启动
- OnnxEmbedder: ONNX 本地语义模型 (bge-small-zh-v1.5)，真正语义相似度
- ModelEmbedder: OpenAI 兼容 /embeddings HTTP API（复用 wiki 的 EMBED_*
  环境变量约定），语义相似度、无需本地模型文件

选择入口: ``backend.memory.embedder_factory.create_embedder``。
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
import threading
import time
from pathlib import Path
from typing import Any, List, Optional, Protocol


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
    - 语义检索用 OnnxEmbedder (bge-small-zh-v1.5) 替代

    ``is_semantic = False``: 检索融合权重与写入路径按字面匹配能力配置。
    """

    #: 字面 n-gram 匹配, 非语义 (T1: RRF 权重据此配置)
    is_semantic = False

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

    def encode_to_bytes(self, text: str) -> bytes:
        """将文本编码为 sqlite-vec 兼容的 float32 little-endian bytes

        Args:
            text: 输入文本

        Returns:
            dimensions * 4 字节的 float32 little-endian 数据
        """
        vector = self.encode(text)
        return struct.pack(f"<{self._dimensions}f", *vector)

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码（HashEmbedder 无网络开销, 逐条编码即可）"""
        return [self.encode(t) for t in texts]


# ---------------------------------------------------------------------------
# OnnxEmbedder (E9-1, P9): ONNX 本地语义嵌入
#
# 模型: bge-small-zh-v1.5 (512 维, 中文优化, BAAI, MIT 授权)。
# 依赖: onnxruntime + tokenizers —— 均为可选依赖, 不进 requirements.txt;
# 懒加载 + 工厂降级保证缺依赖/缺模型文件时回退 HashEmbedder。
#
# 维度兼容: sqlite-vec 虚拟表按维度建表, 256(Hash) 与 512(Onnx) 不混用 ——
# OnnxEmbedder 路径的 VectorStore 使用独立表名 (memories_vec_512),
# 旧 256 维向量随 Hash→Onnx 切换自然失效 (嵌入无迁移意义)。
# ---------------------------------------------------------------------------

#: bge 系列模型 CLS 池化后维度
BGE_SMALL_ZH_DIMENSIONS = 512

#: onnxruntime session 的输入名集合 (按模型实际暴露自适应)
_BGE_INPUT_NAMES = {"input_ids", "attention_mask", "token_type_ids"}


def l2_normalize(vec: List[float]) -> List[float]:
    """L2 归一化 (纯函数, 便于单测)。零向量原样返回。"""
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


def pool_cls_token(last_hidden_state: Any) -> List[float]:
    """取句向量并 L2 归一化 (自适应输出形状)。

    不同 ONNX 导出的输出形状不一:
    - [batch, seq, hidden] — 原始 last_hidden_state → 取 [0][0] (CLS)
    - [batch, hidden]      — 导出时已池化       → 取 [0]
    - [hidden]             — 一维直接用

    纯 duck-typing 逐层降维到标量向量, 不依赖 numpy API —— 单测用
    list 嵌套即可验证。
    """
    arr = last_hidden_state
    # 逐层剥掉 batch/seq 维度, 直到元素是标量
    while hasattr(arr, "__len__") and len(arr) > 0 and hasattr(arr[0], "__len__"):
        arr = arr[0]
    if not hasattr(arr, "__len__") or len(arr) == 0:
        return []
    return l2_normalize([float(v) for v in arr])


class OnnxEmbedder:
    """ONNX 本地语义嵌入器 (bge-small-zh-v1.5)

    依赖 (可选): onnxruntime、tokenizers。
    模型文件: ``<model_dir>/model.onnx`` + ``<model_dir>/tokenizer.json``。

    所有重资源 (ORT session、tokenizer) 懒加载 —— 构造函数只记录路径,
    首次 ``encode`` 时才加载; 加载失败抛出的异常由调用方 (工厂) 捕获降级。

    ``is_semantic = True``: 语义向量质量高于字面哈希 (T1: RRF 权重、
    T2: 写入路径走编码队列)。
    """

    is_semantic = True

    def __init__(
        self,
        model_dir: str,
        dimensions: int = BGE_SMALL_ZH_DIMENSIONS,
        max_length: int = 512,
    ) -> None:
        self._model_dir = model_dir
        self._dimensions = dimensions
        self._max_length = max_length
        self._tokenizer: Any = None
        self._session: Any = None
        self._input_names: List[str] = []
        self._loaded = False

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def loaded(self) -> bool:
        return self._loaded

    def _ensure_loaded(self) -> None:
        """懒加载 tokenizer + ORT session (幂等)。失败抛异常, 由调用方降级。"""
        if self._loaded:
            return


        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = Path(self._model_dir) / "model.onnx"
        tokenizer_path = Path(self._model_dir) / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise FileNotFoundError(
                f"语义嵌入模型不完整: {self._model_dir} (需要 model.onnx + tokenizer.json)"
            )

        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=self._max_length)

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            model_path, sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input_names = [inp.name for inp in self._session.get_inputs()]
        self._loaded = True

    def encode(self, text: str) -> List[float]:
        """将文本编码为 512 维语义向量 (CLS 池化 + L2 归一化)"""
        self._ensure_loaded()

        if not text or not text.strip():
            return [0.0] * self._dimensions

        encoded = self._tokenizer.encode(text)
        ids = list(encoded.ids)
        attention = list(encoded.attention_mask)

        feed: dict = {"input_ids": [ids], "attention_mask": [attention]}
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = [[0] * len(ids)]

        outputs = self._session.run(None, feed)
        # 输出形状随导出方式而异 ([1,seq,hidden] 或已池化 [1,hidden]),
        # pool_cls_token 自适应降维取句向量。
        pooled = pool_cls_token(outputs[0])

        if len(pooled) != self._dimensions:
            raise ValueError(
                f"模型输出维度 {len(pooled)} 与预期 {self._dimensions} 不符"
            )
        return pooled

    def encode_to_bytes(self, text: str) -> bytes:
        """sqlite-vec 兼容的 float32 little-endian bytes"""
        vector = self.encode(text)
        return struct.pack(f"<{self._dimensions}f", *vector)

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码（逐条委托 encode, 懒加载语义不变）"""
        return [self.encode(t) for t in texts]


class ModelEmbedder:
    """基于 OpenAI 兼容 /embeddings API 的语义 Embedder (Round 1)

    对标 hermes-agent：记忆向量检索需要真实语义。wiki 子系统已有成熟的
    OpenAI 兼容 embedding 管线（backend/wiki/embeddings.py），本类把
    同样的端点约定复用到记忆检索 —— 适合不想下载本地 ONNX 模型、
    但已配置 embedding API 的部署形态。

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

        维度在首次成功编码后锁定；建表方（VectorStore）按维度选表
        （embedder_factory 的表名约定），维度变更自然切换新表。
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

        Raises:
            EmbedderError: HTTP 失败 / 熔断打开 / 空文本
        """
        if not text:
            return [0.0] * self.dimensions
        return self.encode_batch([text])[0]

    def encode_to_bytes(self, text: str) -> bytes:
        """sqlite-vec 兼容的 float32 little-endian bytes"""
        vector = self.encode(text)
        return struct.pack(f"<{len(vector)}f", *vector)
