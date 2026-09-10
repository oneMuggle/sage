"""嵌入器工厂 (E9-1, P9)

按配置选择嵌入器实现：

- 缺省: ``HashEmbedder(256)`` —— 零依赖, 字面 n-gram 匹配, 立即可用。
- ``SAGE_EMBEDDER=onnx``: ``OnnxEmbedder(512)`` —— ONNX 本地语义模型
  (bge-small-zh-v1.5), 真正语义相似度。需要:
    1. 可选依赖 onnxruntime + tokenizers 已安装;
    2. 模型文件目录 (``SAGE_EMBEDDING_MODEL_DIR`` 或 userData/models/bge-small-zh-v1.5)
       内含 model.onnx + tokenizer.json。

任一条件不满足 → 记 warning 并降级 HashEmbedder。降级是显式设计:
嵌入属增强能力, 不应让缺依赖阻塞记忆系统启动。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from backend.memory.embedder import (
    BGE_SMALL_ZH_DIMENSIONS,
    HashEmbedder,
    OnnxEmbedder,
)

logger = logging.getLogger(__name__)

#: ONNX 语义模型的缺省目录名 (相对 userData/models)
DEFAULT_ONNX_MODEL_DIR_NAME = "bge-small-zh-v1.5"

#: 向量表后缀 —— 维度不同不能共用虚拟表
ONNX_VEC_TABLE = f"memories_vec_{BGE_SMALL_ZH_DIMENSIONS}"
HASH_VEC_TABLE = "memories_vec"


def onnx_model_dir() -> str:
    """解析语义模型目录: SAGE_EMBEDDING_MODEL_DIR > SAGE_USER_DATA_DIR/models > bundled。"""
    explicit = os.environ.get("SAGE_EMBEDDING_MODEL_DIR")
    if explicit:
        return explicit
    user_data_dir = os.environ.get("SAGE_USER_DATA_DIR")
    if user_data_dir:
        return os.path.join(user_data_dir, "models", DEFAULT_ONNX_MODEL_DIR_NAME)
    # 与 theme_storage 同模式: dev/tests 无 SAGE_USER_DATA_DIR 时用
    # 仓库内可写路径 (backend/data/models)。
    return str(Path(__file__).resolve().parent.parent / "data" / "models" / DEFAULT_ONNX_MODEL_DIR_NAME)


def onnx_model_ready(model_dir: str) -> bool:
    """模型文件是否齐备 (model.onnx + tokenizer.json)。"""
    base = Path(model_dir)
    return (base / "model.onnx").is_file() and (base / "tokenizer.json").is_file()


def create_embedder() -> Any:  # 返回 HashEmbedder 或 OnnxEmbedder
    """按配置创建嵌入器; ONNX 不可用时降级 HashEmbedder。

    Returns:
        Embedder 实例。``embedder.dimensions`` 同时决定向量虚拟表
        (调用方据维度选择表名, 见 MemoryAdapter 装配)。
    """
    if os.environ.get("SAGE_EMBEDDER", "").strip().lower() == "onnx":
        model_dir = onnx_model_dir()
        if not onnx_model_ready(model_dir):
            logger.warning(
                "SAGE_EMBEDDER=onnx 但模型文件不齐 (%s)，降级 HashEmbedder。"
                "请放置 model.onnx + tokenizer.json 或安装模型包。",
                model_dir,
            )
        else:
            try:
                embedder = OnnxEmbedder(model_dir=model_dir)
                # 预热: 首条真实编码在请求路径上代价高 (~模型加载), 启动时空跑一次
                embedder.encode("初始化")
                logger.info(
                    "语义嵌入已启用: OnnxEmbedder dims=%s model=%s",
                    embedder.dimensions,
                    model_dir,
                )
                return embedder
            except ImportError as exc:
                logger.warning(
                    "onnx 依赖缺失 (%s)，降级 HashEmbedder。"
                    "可选安装: pip install onnxruntime tokenizers",
                    exc,
                )
            except Exception as exc:  # noqa: BLE001 — 模型损坏等一律降级
                logger.warning("OnnxEmbedder 初始化失败 (%s)，降级 HashEmbedder。", exc)

    return HashEmbedder(dimensions=256)
