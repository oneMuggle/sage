"""RichMedia 契约与工具结果信封单元测试"""

import pytest

pytestmark = [pytest.mark.unit]


def _sample_media():
    from backend.domain.media import RichMedia

    return RichMedia(
        id="abc123",
        kind="diagram",
        mime_type="image/svg+xml",
        api_url="/api/v1/media/abc123",
        format="svg",
        title="render_diagram",
        source="mcp:drawio",
        interactive=True,
    )


def test_media_envelope_shape():
    from backend.domain.media import media_envelope

    env = media_envelope("渲染完成", [_sample_media()])
    assert env["text"] == "渲染完成"
    assert env["metadata"]["mediaRefs"][0]["api_url"] == "/api/v1/media/abc123"
    assert env["metadata"]["richMedia"][0]["interactive"] is True
    assert "base64" not in str(env)


def test_rich_media_to_dict_keys():
    d = _sample_media().to_dict()
    assert set(d) == {
        "id", "kind", "mime_type", "api_url",
        "format", "title", "source", "interactive",
    }
    assert d["kind"] == "diagram"
    assert d["mime_type"] == "image/svg+xml"


def test_media_envelope_merges_extra_metadata():
    from backend.domain.media import media_envelope

    env = media_envelope("ok", [], extra_metadata={"imageData": "legacy-fallback"})
    assert env["metadata"]["imageData"] == "legacy-fallback"
    assert env["metadata"]["mediaRefs"] == []
    assert env["metadata"]["richMedia"] == []


def test_media_envelope_empty_media():
    from backend.domain.media import media_envelope

    env = media_envelope("plain", [])
    assert env["text"] == "plain"
    assert env["metadata"]["mediaRefs"] == []
