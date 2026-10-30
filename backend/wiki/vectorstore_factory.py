"""Wiki 向量库后端选择（JSON 默认 / HNSW 可选）。

``SAGE_WIKI_VECTOR_BACKEND=hnsw`` 时优先使用 hnswlib 索引；未安装 hnswlib
或取值非法时回退 JSON ``VectorStore``，保证打包环境（Win7 无 hnswlib wheel）
仍可运行。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .vectorstore import VectorStore

logger = logging.getLogger(__name__)

ENV_KEY = "SAGE_WIKI_VECTOR_BACKEND"
VALID_BACKENDS = ("json", "hnsw")


def backend_name() -> str:
    value = (os.environ.get(ENV_KEY) or "json").strip().lower()
    return value if value in VALID_BACKENDS else "json"


def open_vector_store(project_root: Path, dim: int) -> Any:
    """Open the configured wiki vector store for ``project_root``."""
    if backend_name() == "hnsw":
        try:
            from .vectorstore_hnsw import HNSWVectorStore

            return HNSWVectorStore.open(project_root, dim)
        except ImportError:
            logger.warning(
                "wiki vector backend 'hnsw' requested but hnswlib is unavailable; "
                "falling back to JSON vector store"
            )
    return VectorStore.open(project_root, dim)
