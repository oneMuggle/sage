"""McpTool 图片结果落盘为媒体引用 —— 单元测试"""

import base64

import pytest

pytestmark = [pytest.mark.unit]


class _FakePool:
    def __init__(self, response):
        self._response = response

    def call_tool(self, server, tool, args):
        return self._response


def _make_tool(response):
    from backend.mcp.tool import McpTool

    return McpTool(
        _FakePool(response),
        "drawio",
        {"name": "render_diagram", "description": "", "inputSchema": {}},
    )


def _png_b64() -> str:
    return base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()


def _install_store(monkeypatch, tmp_path):
    from backend.services.multimodal.media_store import MediaStore

    store = MediaStore(tmp_path)
    monkeypatch.setattr(
        "backend.services.multimodal.media_store.MediaStore", lambda: store
    )
    return store


def test_mcp_image_persisted_as_media_ref(monkeypatch, tmp_path):
    _install_store(monkeypatch, tmp_path)
    tool = _make_tool(
        {
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "image", "data": _png_b64(), "mimeType": "image/png"},
            ]
        }
    )

    res = tool.execute()

    assert res.success is True
    assert isinstance(res.content, dict)
    ref = res.content["metadata"]["mediaRefs"][0]
    assert ref["api_url"].startswith("/api/v1/media/")
    assert ref["kind"] == "image"
    assert "base64" not in str(res.content)
    assert res.content["text"] == "ok"


def test_mcp_svg_media_is_interactive_diagram(monkeypatch, tmp_path):
    _install_store(monkeypatch, tmp_path)
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    tool = _make_tool(
        {
            "content": [
                {
                    "type": "image",
                    "data": base64.b64encode(svg).decode(),
                    "mimeType": "image/svg+xml",
                }
            ]
        }
    )

    res = tool.execute()

    assert res.success is True
    rich = res.content["metadata"]["richMedia"][0]
    assert rich["kind"] == "diagram"
    assert rich["mime_type"] == "image/svg+xml"
    assert rich["interactive"] is True
    assert rich["source"] == "mcp:drawio"


def test_mcp_image_persist_failure_falls_back_to_image_data(monkeypatch, tmp_path):
    tool = _make_tool(
        {
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "image", "data": _png_b64(), "mimeType": "image/png"},
            ]
        }
    )

    def _boom():
        raise RuntimeError("disk full")

    monkeypatch.setattr(
        "backend.services.multimodal.media_store.MediaStore", lambda: _boom()
    )

    res = tool.execute()

    assert res.success is True
    assert "imageData" in res.content["metadata"]
    assert res.content["metadata"]["imageData"].startswith("data:image/png;base64,")
    assert "mediaRefs" not in res.content["metadata"]


def test_mcp_text_only_result_unchanged(monkeypatch, tmp_path):
    _install_store(monkeypatch, tmp_path)
    tool = _make_tool({"content": [{"type": "text", "text": "hello"}]})

    res = tool.execute()

    assert res.success is True
    assert res.content == "hello"
