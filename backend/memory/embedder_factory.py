"""嵌入器工厂 (E9-1, P9 + Round 1)

按配置选择嵌入器实现：

- 缺省: ``HashEmbedder(256)`` —— 零依赖, 字面 n-gram 匹配, 立即可用。
- ``SAGE_EMBEDDER=onnx``: ``OnnxEmbedder(512)`` —— ONNX 本地语义模型
  (bge-small-zh-v1.5), 真正语义相似度。需要:
    1. 可选依赖 onnxruntime + tokenizers 已安装;
    2. 模型文件目录 (``SAGE_EMBEDDING_MODEL_DIR`` 或 userData/models/bge-small-zh-v1.5)
       内含 model.onnx + tokenizer.json。
- ``SAGE_EMBEDDER=model``: ``ModelEmbedder`` —— OpenAI 兼容 /embeddings
  HTTP API (Round 1, 复用 wiki 的 EMBED_BASE_URL/EMBED_API_KEY/EMBED_MODEL
  环境变量约定)。适合不想下载本地模型的部署; 端点不可用时熔断降级。

任一条件不满足 → 记 warning 并降级 HashEmbedder。降级是显式设计:
嵌入属增强能力, 不应让缺依赖阻塞记忆系统启动。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from backend.memory.embedder import (
    BGE_SMALL_ZH_DIMENSIONS,
    Embedder,
    HashEmbedder,
    ModelEmbedder,
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


def _preferred_mode_from_settings() -> str:
    """读 settings 持久化的嵌入器偏好 (embedding.mode)；无则空串。

    settings 不可用时静默返回空串 (调用方回退 env / hash)。
    """
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get("embedding_mode")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    except Exception:  # noqa: BLE001 — settings 缺失属正常路径
        pass
    return ""


def create_embedder(preferred_mode: Optional[str] = None) -> Embedder:
    """按配置创建嵌入器; ONNX/HTTP 端点不可用时降级 HashEmbedder。

    偏好解析顺序: preferred_mode 参数 (API 显式切换) > settings
    (embedding.mode) > SAGE_EMBEDDER 环境变量 > hash (缺省)。

    Returns:
        Embedder 实例。``embedder.dimensions`` 同时决定向量虚拟表
        (调用方据维度选择表名, 见 MemoryAdapter 装配)。
    """
    choice = (preferred_mode or "").strip().lower()
    if not choice:
        choice = _preferred_mode_from_settings()
    if not choice:
        choice = os.environ.get("SAGE_EMBEDDER", "").strip().lower()

    if choice == "onnx":
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

    if choice == "model":
        embedder = ModelEmbedder.from_env()
        if embedder is not None:
            logger.info(
                "语义嵌入已启用: ModelEmbedder dims=%s base_url=%s model=%s",
                embedder.dimensions,
                embedder._base_url,
                embedder._model,
            )
            return embedder
        logger.warning(
            "SAGE_EMBEDDER=model 但未配置 EMBED_BASE_URL/EMBED_MODEL，"
            "降级 HashEmbedder。"
        )

    return HashEmbedder(dimensions=256)
