"""RapidOCR 引擎（ONNX Runtime + PP-OCR 模型）。

依赖均为可选：
- ``rapidocr``（3.x，支持 PP-OCRv4/v5/v6）或 ``rapidocr-onnxruntime``（legacy）；
- ``onnxruntime``。

模型目录优先级：
``SAGE_OCR_MODEL_DIR`` > ``SAGE_USER_DATA_DIR/models/rapidocr`` >
``backend/data/models/rapidocr``。目录内约定 ``det.onnx`` / ``rec.onnx`` /
``cls.onnx``（cls 可选）；不齐时回退到包内默认模型解析（离线部署时应显式
放置模型，避免运行时联网下载）。

本模块所有第三方 import 都在方法内完成，未安装时不影响主程序启动。
"""

from __future__ import annotations

import contextlib
import inspect
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..models import (
    QUALITY_EMPTY,
    QUALITY_LOW_CONFIDENCE,
    QUALITY_OK,
    OcrLine,
    OcrOptions,
    OcrResult,
)

_MODEL_DIR_ENV = "SAGE_OCR_MODEL_DIR"


class RapidOcrEngine:
    """RapidOCR 后端（懒加载、线程安全初始化）。"""

    name = "rapidocr"

    def __init__(self) -> None:
        self._engine: Any = None
        self._lock = threading.Lock()
        self._call_lock = threading.Lock()

    def available(self) -> Tuple[bool, str]:
        try:
            _import_rapidocr()
        except Exception:  # noqa: BLE001 — 缺失/损坏都归为不可用
            return False, "rapidocr 未安装（pip install rapidocr onnxruntime）"
        model_dir = resolve_model_dir()
        if model_dir is not None and not _models_ready(model_dir):
            return False, "RapidOCR 模型文件不齐（需要 det.onnx + rec.onnx）"
        return True, ""

    def recognize(self, image_bytes: bytes, opts: OcrOptions) -> OcrResult:
        engine = self._ensure_engine()
        with self._call_lock:
            _apply_runtime_options(engine, opts)
            raw = self._run(engine, image_bytes)
        lines = _parse_result(raw, opts.min_confidence)
        text = "\n".join(line.text for line in lines if line.text)
        if not text.strip():
            quality = QUALITY_EMPTY
        elif all(line.confidence < max(opts.min_confidence + 0.2, 0.6) for line in lines):
            quality = QUALITY_LOW_CONFIDENCE
        else:
            quality = QUALITY_OK
        return OcrResult(
            text=text,
            lines=tuple(lines),
            engine=self.name,
            lang=opts.lang,
            quality=quality,
        )

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is None:
                self._engine = _create_engine()
            return self._engine

    @staticmethod
    def _run(engine: Any, image_bytes: bytes) -> Any:
        try:
            return engine(image_bytes)
        except (TypeError, ValueError, AttributeError):
            # 部分版本不接受 bytes，退回临时文件路径
            tmp_path = _write_temp(image_bytes)
            try:
                return engine(tmp_path)
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

def _import_rapidocr() -> Any:
    try:
        from rapidocr import RapidOCR  # type: ignore

        return RapidOCR
    except ImportError:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        return RapidOCR


def _create_engine() -> Any:
    rapidocr_cls = _import_rapidocr()
    model_dir = resolve_model_dir()
    try:
        supports_params = "params" in inspect.signature(rapidocr_cls.__init__).parameters
    except (TypeError, ValueError):
        supports_params = False
    if supports_params:
        # 3.x：通过 params 指定默认模型与预处理尺寸；单次调用会再按
        # OcrOptions 覆盖 max_side_len / use_cls。
        params: dict = {
            "Global.max_side_len": 1280,
            "Global.use_cls": False,
        }
        params.update(_model_params(model_dir))
        return rapidocr_cls(params=params)
    kwargs = _model_kwargs(model_dir)
    try:
        return rapidocr_cls(**kwargs) if kwargs else rapidocr_cls()
    except TypeError:
        # legacy 与期望参数不同：退回默认构造（使用包内模型）
        return rapidocr_cls()


def _apply_runtime_options(engine: Any, opts: OcrOptions) -> None:
    """按单次请求覆盖 RapidOCR 的预处理参数（调用方持锁）。"""
    with contextlib.suppress(Exception):
        engine.max_side_len = opts.max_side
    with contextlib.suppress(Exception):
        engine.use_cls = opts.use_cls


def resolve_model_dir() -> Optional[Path]:
    """显式/已存在的模型目录；都没有时返回 None（使用包内默认模型）。"""
    explicit = os.environ.get(_MODEL_DIR_ENV, "").strip()
    if explicit:
        return Path(explicit)
    user_data = os.environ.get("SAGE_USER_DATA_DIR", "").strip()
    if user_data:
        candidate = Path(user_data) / "models" / "rapidocr"
        return candidate if candidate.is_dir() else None
    repo_dir = Path(__file__).resolve().parents[3] / "data" / "models" / "rapidocr"
    return repo_dir if repo_dir.is_dir() else None

def _models_ready(model_dir: Path) -> bool:
    return (model_dir / "det.onnx").is_file() and (model_dir / "rec.onnx").is_file()


def _model_params(model_dir: Optional[Path]) -> dict:
    """3.x params 形态的模型路径覆盖。"""
    if model_dir is None or not _models_ready(model_dir):
        return {}
    params = {
        "Det.model_path": str(model_dir / "det.onnx"),
        "Rec.model_path": str(model_dir / "rec.onnx"),
    }
    cls_path = model_dir / "cls.onnx"
    if cls_path.is_file():
        params["Cls.model_path"] = str(cls_path)
    return params


def _model_kwargs(model_dir: Optional[Path]) -> dict:
    if model_dir is None or not _models_ready(model_dir):
        return {}
    kwargs = {
        "det_model_path": str(model_dir / "det.onnx"),
        "rec_model_path": str(model_dir / "rec.onnx"),
    }
    cls_path = model_dir / "cls.onnx"
    if cls_path.is_file():
        kwargs["cls_model_path"] = str(cls_path)
    return kwargs


def _write_temp(image_bytes: bytes) -> str:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        handle.write(image_bytes)
        return handle.name
    finally:
        handle.close()


def _parse_result(raw: Any, min_confidence: float) -> List[OcrLine]:
    """兼容 RapidOCR 3.x（对象）与 legacy（tuple/list）两种返回形态。"""
    texts: List[Any] = []
    scores: List[Any] = []
    boxes: List[Any] = []

    if hasattr(raw, "txts"):
        # 3.x 的 txts/scores/boxes 可能是 numpy 数组，不能直接 ``or []``
        texts = _as_list(getattr(raw, "txts", None))
        scores = _as_list(getattr(raw, "scores", None))
        boxes = _as_list(getattr(raw, "boxes", None))
    else:
        payload = raw
        if isinstance(raw, tuple) and raw:
            payload = raw[0]
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, (list, tuple)) and len(item) >= 3:  # noqa: UP038 — py3.8
                    boxes.append(item[0])
                    texts.append(item[1])
                    scores.append(item[2])

    lines: List[OcrLine] = []
    for index, text in enumerate(texts):
        value = str(text).strip()
        if not value:
            continue
        try:
            score = float(scores[index])
        except (IndexError, TypeError, ValueError):
            score = 0.0
        if score < min_confidence:
            continue
        bbox = _box_from_points(boxes[index]) if index < len(boxes) else None
        lines.append(OcrLine(text=value, confidence=score, bbox=bbox))
    return lines


def _as_list(value: Any) -> List[Any]:
    """把 list/tuple/numpy 数组统一成 list；None 返回空列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return []


def _box_from_points(points: Any) -> Optional[Tuple[int, int, int, int]]:
    try:
        coords = list(points)
        xs = [int(point[0]) for point in coords]
        ys = [int(point[1]) for point in coords]
        if not xs or not ys:
            return None
        return (min(xs), min(ys), max(xs), max(ys))
    except (TypeError, ValueError, IndexError):
        return None
