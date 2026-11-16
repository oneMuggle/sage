"""工具结果 JSON 序列化兜底单测（2026-11-15）。

`MediaRef` 等 dataclass 曾被 `default=str` 变成 Python repr 字符串，
前端拿不到 `id/mime_type`，图片工具无法内联渲染。
"""

import json

import pytest

from backend.core.legacy.agent import _json_default
from backend.services.multimodal.media_store import MediaKind, MediaRef

pytestmark = pytest.mark.unit


def _media_ref() -> MediaRef:
    return MediaRef(
        id="abc123def456",
        kind=MediaKind.IMAGE,
        mime_type="image/png",
        file_path="2026/11/16/abc123def456.png",
        file_size=68,
        created_at="2026-11-16T00:00:00+00:00",
        source="pdf_figure",
        metadata={"page": 12},
    )


def test_media_ref_serializes_to_object_not_repr():
    payload = json.loads(json.dumps({"media_refs": [_media_ref()]}, default=_json_default))
    ref = payload["media_refs"][0]
    assert ref["id"] == "abc123def456"
    assert ref["kind"] == "image"
    assert ref["mime_type"] == "image/png"
    assert ref["source"] == "pdf_figure"
    assert ref["metadata"]["page"] == 12


def test_unknown_object_falls_back_to_str():
    payload = json.loads(json.dumps({"value": object()}, default=_json_default))
    assert payload["value"].startswith("<object object at")
