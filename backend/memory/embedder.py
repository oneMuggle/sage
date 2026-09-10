"""Embedder - 文本向量化接口

将文本转换为固定维度的浮点向量，供向量检索使用。

提供两种实现:
- HashEmbedder: 基于字符 n-gram 哈希，零依赖，适合快速启动
- OnnxEmbedder: ONNX 本地语义模型 (bge-small-zh-v1.5)，真正语义相似度

选择入口: ``backend.memory.embedder_factory.create_embedder``。
"""

from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path
from typing import Any, List, Protocol


class Embedder(Protocol):
    """Embedder 协议 — 将文本编码为浮点向量"""

    @property
    def dimensions(self) -> int:
        """向量维度"""
        ...

    def encode(self, text: str) -> List[float]:
        """将文本编码为固定维度的浮点向量"""
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
