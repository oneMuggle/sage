"""Office 工具共用小工具：输出预算裁剪 + LLM 参数强类型转换。

原先这些逻辑散落在 ``office_pdf_tool.py`` 与 ``office_template_tool.py``
里（后者的 ``_bounded`` 与前者逐字重复）。抽到一处，两个工具共用同一套
语义，避免「一个工具改了、另一个没改」的行为漂移。

对外一律用**公开名**（无下划线前缀）—— 它们已经是跨模块的共享契约。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def bounded_output(data: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    """超 ``max_bytes`` 时退化为 bounded head，语义同 tool_service。"""
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    raw = serialized.encode("utf-8")
    if len(raw) <= max_bytes:
        return data
    head = raw[:max_bytes].decode("utf-8", errors="ignore")
    return {"truncated": True, "max_output_bytes": max_bytes, "head": head}


def serialized_size(data: Dict[str, Any]) -> int:
    """JSON 序列化后的字节数（用于输出预算计算）。"""
    return len(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))


def fit_image_output_budget(data: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    """在输出预算内保住结构 —— 优先丢图片像素，而不是截断整个 JSON。

    ``bounded_output`` 会把响应砍成 ``{"truncated": true, "head": …}`` ——
    对 LLM 来说等于什么都没读到。这里先按「大图优先」逐张剥离 ``data_url``，
    并把被剥离的张数记进该页的 ``images_omitted``，让调用方知道
    「文档里有图，但像素没带回来」。

    文本/表格本身超预算时不在这里处理 —— 那是 ``bounded_output`` 的既有职责。
    """
    pages = data.get("pages")
    if not isinstance(pages, list):
        return data
    entries = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        images = page.get("images")
        if not isinstance(images, list):
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            url = image.get("data_url")
            if isinstance(url, str):
                entries.append((len(url), page, image))
    if not entries:
        return data
    entries.sort(key=lambda item: item[0], reverse=True)
    size = serialized_size(data)
    for length, page, image in entries:
        if size <= max_bytes:
            break
        image.pop("data_url", None)
        page["images_omitted"] = int(page.get("images_omitted") or 0) + 1
        # 粗估被删字段的体积（含逗号与引号）。
        size -= length + 16
    return data


def coerce_bool(value: Any) -> Optional[bool]:
    """把 LLM 传来的参数严格解释成 bool；无法解释返回 ``None``。

    ``bool("false")`` 是 ``True`` —— 直接转换会让「模型显式说不要图片」
    变成「要图片」。因此这里只接受真正的 bool、0/1 和明确的字符串。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    return None


def coerce_int(value: Any) -> Optional[int]:
    """把 LLM 传来的参数严格解释成 int；无法解释返回 ``None``。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


__all__ = [
    "bounded_output",
    "coerce_bool",
    "coerce_int",
    "fit_image_output_budget",
    "serialized_size",
]
