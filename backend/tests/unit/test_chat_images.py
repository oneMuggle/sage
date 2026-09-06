"""G6 聊天图片输入单元测试：data URL 校验 + 多模态消息构造。"""

from __future__ import annotations

import base64

import pytest

from backend.api.legacy_routes import _validate_chat_images

pytestmark = [pytest.mark.unit]


def _png_data_url(size_hint: int = 16) -> str:
    payload = base64.b64encode(b"x" * size_hint).decode()
    return f"data:image/png;base64,{payload}"


def _jpeg_data_url() -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(b'y' * 16).decode()}"


def test_valid_images_pass():
    assert _validate_chat_images([_png_data_url(), _jpeg_data_url()]) is None


def test_rejects_non_data_url():
    error = _validate_chat_images(["https://example.com/a.png"])
    assert error is not None
    assert "images[0]" in error


def test_rejects_non_image_mime():
    error = _validate_chat_images(["data:text/html;base64,AAAA"])
    assert error is not None
    assert "png/jpeg/webp/gif" in error


def test_rejects_missing_payload():
    error = _validate_chat_images(["data:image/png;base64,"])
    assert error is not None
    assert "缺少 base64" in error


def test_rejects_bad_base64():
    error = _validate_chat_images(["data:image/png;base64,!!!not-base64!!!"])
    assert error is not None
    assert "解码失败" in error


def test_rejects_over_count():
    images = [_png_data_url() for _ in range(5)]
    error = _validate_chat_images(images)
    assert error is not None
    assert "上限 4" in error


def test_rejects_oversize_image():
    big = _png_data_url(5 * 1024 * 1024 + 100)
    error = _validate_chat_images([big])
    assert error is not None
    assert "5 MiB" in error


def test_multimodal_message_shape():
    """构造逻辑锁定：text 在前，image_url 依序跟随（OpenAI 分段格式）。"""
    images = [_png_data_url(), _jpeg_data_url()]
    message = "看这张图"
    multimodal = {
        "role": "user",
        "content": [
            {"type": "text", "text": message},
            *[
                {"type": "image_url", "image_url": {"url": image_url}}
                for image_url in images
            ],
        ],
    }
    assert multimodal["content"][0]["text"] == message
    assert [seg["image_url"]["url"] for seg in multimodal["content"][1:]] == images
