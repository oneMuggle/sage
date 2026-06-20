"""Embedder - 文本向量化接口

将文本转换为固定维度的浮点向量，供向量检索使用。

提供两种实现:
- HashEmbedder: 基于字符 n-gram 哈希，零依赖，适合快速启动
- (未来) ModelEmbedder: 基于 sentence-transformers 等 ML 模型，语义更准确
"""

import hashlib
import math
import struct
from typing import Protocol


class Embedder(Protocol):
    """Embedder 协议 — 将文本编码为浮点向量"""

    @property
    def dimensions(self) -> int:
        """向量维度"""
        ...

    def encode(self, text: str) -> list[float]:
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
    - 未来可升级到 ModelEmbedder 获得真正的语义相似度
    """

    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def encode(self, text: str) -> list[float]:
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
        ngrams: list[str] = []
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
