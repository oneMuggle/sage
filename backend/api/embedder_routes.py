"""
嵌入器状态与切换 API (B1, P11)

- GET  /api/v1/memory/embedder/status — 当前嵌入器类型/维度/表名/模型目录
- POST /api/v1/memory/embedder/select — 运行时切换嵌入器

切换语义: settings 持久化 ``embedding_mode`` ("onnx"/"hash") 后, 立即对
``app.state.memory_adapter`` 执行 ``reconfigure()`` —— 替换 embedder 并按
新维度重建向量虚拟表 (Hash=memories_vec, Onnx=memories_vec_512, 互不混用)。
若 ONNX 依赖/模型缺失, ``create_embedder("onnx")`` 自动降级 Hash —— 响应
返回实际生效类型, 前端据此提示。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.memory.embedder_factory import (
    create_embedder,
    onnx_model_dir,
    onnx_model_ready,
)

router = APIRouter(prefix="/memory/embedder", tags=["memory-embedder"])

_VALID_MODES = ("onnx", "hash")


def _status_payload(request: Request) -> dict:
    adapter = getattr(request.app.state, "memory_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="MemoryAdapter 未装配")
    embedder = getattr(adapter, "embedder", None)
    if embedder is None:
        raise HTTPException(status_code=503, detail="embedder 未初始化")
    model_dir = onnx_model_dir()
    vector_store = getattr(adapter, "vector_store", None)
    return {
        "type": type(embedder).__name__,
        "semantic": bool(getattr(embedder, "is_semantic", False)),
        "dimensions": embedder.dimensions,
        "table": getattr(vector_store, "table_name", None),
        "model_dir": model_dir,
        "model_ready": onnx_model_ready(model_dir),
    }


@router.get("/status")
def get_embedder_status(request: Request) -> dict:
    return _status_payload(request)


@router.post("/select")
def select_embedder(request: Request, payload: dict) -> dict:
    """切换嵌入器: mode = "onnx" | "hash"。settings 持久化 + 热重载向量栈。"""
    mode = (payload.get("mode") or "").strip().lower()
    if mode not in _VALID_MODES:
        raise HTTPException(status_code=422, detail=f"无效 mode: {mode!r}")

    adapter = getattr(request.app.state, "memory_adapter", None)
    if adapter is None or not hasattr(adapter, "reconfigure"):
        raise HTTPException(status_code=503, detail="MemoryAdapter 未装配")

    from backend.data.settings_repo import SettingsRepository

    SettingsRepository().set("embedding_mode", mode, value_type="string")

    embedder = create_embedder(preferred_mode=mode)
    adapter.reconfigure(embedder)

    result = _status_payload(request)
    result["mode"] = mode
    return result
