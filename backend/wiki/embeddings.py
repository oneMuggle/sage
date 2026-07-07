"""Markdown 分块和嵌入。

实现 Markdown 内容的智能分块，以及嵌入向量的 HTTP 请求构建和响应解析。
"""
from typing import Dict, List

import json
from dataclasses import dataclass

# 常量
DEFAULT_CHUNK_SIZE = 500  # 目标块大小（字符数）
DEFAULT_CHUNK_OVERLAP = 50  # 块重叠（字符数）


@dataclass
class EmbeddingConfig:
    """嵌入配置。"""

    base_url: str
    api_key: str
    model: str
    dim: int = 1536  # 向量维度（text-embedding-3-small 默认）


@dataclass
class EmbedHttpRequest:
    """嵌入 HTTP 请求。"""

    url: str
    method: str  # "POST"
    headers: Dict[str, str]
    body: dict


def chunk_markdown(content: str, target_chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[str]:
    """将 Markdown 内容分块。

    按段落分割，合并短段落，分割长段落，保持语义完整性。

    Args:
        content: Markdown 内容
        target_chunk_size: 目标块大小（字符数）

    Returns:
        list[str]: 分块后的文本列表
    """
    if not content:
        return []

    # 按双换行分割为段落
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)

        # 如果当前块加上新段落超过目标大小
        if current_len + (2 if current_len > 0 else 0) + para_len > target_chunk_size:
            # 刷新当前块
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_len = 0

            # 如果单个段落超过目标大小，分割它
            if para_len > target_chunk_size:
                chunks.extend(_split_long_paragraph(para, target_chunk_size, DEFAULT_CHUNK_OVERLAP))
            else:
                current_chunk.append(para)
                current_len = para_len
        else:
            current_chunk.append(para)
            current_len += (2 if current_len > 0 else 0) + para_len

    # 刷新最后一个块
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def _split_long_paragraph(text: str, chunk_size: int, overlap: int) -> List[str]:
    """分割长段落。

    使用滑动窗口分割长文本，保持重叠以保持上下文。

    Args:
        text: 长文本
        chunk_size: 块大小
        overlap: 重叠大小

    Returns:
        list[str]: 分割后的文本块
    """
    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])

        if end == text_len:
            break

        # 前进 chunk_size - overlap
        start += chunk_size - overlap

    return chunks


def build_embed_request(config: EmbeddingConfig, texts: List[str]) -> EmbedHttpRequest:
    """构建嵌入 HTTP 请求。

    Args:
        config: 嵌入配置
        texts: 要嵌入的文本列表

    Returns:
        EmbedHttpRequest: HTTP 请求
    """
    url = f"{config.base_url}/embeddings"
    headers = {"Content-Type": "application/json"}

    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    body = {"model": config.model, "input": texts}

    return EmbedHttpRequest(url=url, method="POST", headers=headers, body=body)


def parse_embed_response(body: str, expected_dim: int = 0) -> List[List[float]]:
    """解析嵌入 HTTP 响应。

    Args:
        body: HTTP 响应体（JSON 字符串）
        expected_dim: 期望的向量维度（0 表示不检查）

    Returns:
        list[list[float]]: 嵌入向量列表

    Raises:
        ValueError: 如果向量维度不匹配
    """
    data = json.loads(body)
    embeddings = []

    for item in data.get("data", []):
        vector = item.get("embedding", [])

        if expected_dim > 0 and len(vector) != expected_dim:
            raise ValueError(f"向量维度不匹配: 期望 {expected_dim}, 实际 {len(vector)}")

        embeddings.append(vector)

    return embeddings
