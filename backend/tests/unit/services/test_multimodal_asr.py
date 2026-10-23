"""R120 — ASR（语音转写）能力单元测试。

覆盖：build_request 的 file_path / file_content 双路径、R22-D8 扩展名
白名单与 25MB 上限两道安全闸、multipart files/data 结构、api_key 头、
language 可选；parse_response 非 200 错误与 text/language 提取。
"""

from __future__ import annotations

import pytest

from backend.services.multimodal.asr import ASRCapability
from backend.services.multimodal.capability import AIHttpResponse, CapabilityConfig

pytestmark = pytest.mark.unit


def _config(api_key: str = "") -> CapabilityConfig:
    return CapabilityConfig(
        base_url="https://api.example.com/v1", api_key=api_key, model="whisper-1"
    )


def _resp(status_code=200, content=b"", json=None):
    return AIHttpResponse(status_code=status_code, content=content, json=json)


# ---------------------------------------------------------------------------
# build_request: file_content 路径
# ---------------------------------------------------------------------------


def test_build_request_with_file_content():
    req = ASRCapability().build_request(
        _config(api_key="sk-a"), file_content=b"ogg-bytes", language="zh"
    )
    assert req.url == "https://api.example.com/v1/audio/transcriptions"
    assert req.headers["Authorization"] == "Bearer sk-a"
    assert req.files == {"file": ("upload.ogg", b"ogg-bytes")}
    assert req.data == {"model": "whisper-1", "language": "zh"}


def test_language_omitted_by_default():
    req = ASRCapability().build_request(_config(), file_content=b"x")
    assert req.data == {"model": "whisper-1"}
    assert "Authorization" not in req.headers


# --- build_request: 安全闸 ---


def test_content_over_limit_rejected():
    big = b"x" * (ASRCapability.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ValueError, match="上限"):
        ASRCapability().build_request(_config(), file_content=big)


def test_disallowed_extension_rejected():
    # 扩展名闸只在仅传 file_path 时生效（与生产调用形态一致）
    with pytest.raises(ValueError, match="不支持的音频扩展名"):
        ASRCapability().build_request(_config(), file_path="C:/tmp/notes.txt")


def test_extension_error_lists_allowed_set():
    with pytest.raises(ValueError, match="不支持的音频扩展名") as excinfo:
        ASRCapability().build_request(_config(), file_path="C:/tmp/x.docx")
    message = str(excinfo.value)
    for ext in (".mp3", ".wav", ".flac"):
        assert ext in message


def test_allowed_extension_reads_file(tmp_path):
    audio = tmp_path / "clip.mp3"
    audio.write_bytes(b"mp3-payload")
    req = ASRCapability().build_request(_config(), file_path=str(audio))
    assert req.files == {"file": ("clip.mp3", b"mp3-payload")}


def test_uppercase_extension_allowed(tmp_path):
    audio = tmp_path / "CLIP.MP3"
    audio.write_bytes(b"y")
    req = ASRCapability().build_request(_config(), file_path=str(audio))
    assert req.files["file"][0] == "CLIP.MP3"


def test_oversized_file_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(ASRCapability, "MAX_UPLOAD_BYTES", 4)
    audio = tmp_path / "big.wav"
    audio.write_bytes(b"123456")
    with pytest.raises(ValueError, match="上限"):
        ASRCapability().build_request(_config(), file_path=str(audio))


def test_neither_path_nor_content_rejected():
    with pytest.raises(ValueError, match="必须提供"):
        ASRCapability().build_request(_config())


# ---------------------------------------------------------------------------
# parse_response
# ---------------------------------------------------------------------------


def test_parse_response_non_200_raises():
    with pytest.raises(ValueError, match="ASR upstream returned 502"):
        ASRCapability().parse_response(_resp(502, content=b"bad gateway"))


def test_parse_response_extracts_text_and_language():
    out = ASRCapability().parse_response(
        _resp(200, json={"text": "你好世界", "language": "zh"})
    )
    assert out == {"text": "你好世界", "language": "zh"}


def test_parse_response_missing_keys_default_empty():
    out = ASRCapability().parse_response(_resp(200, json={}))
    assert out == {"text": "", "language": ""}


def test_kind_and_settings_slot():
    assert ASRCapability.settings_slot == "asrModel"
    assert len(ASRCapability.ALLOWED_EXTENSIONS) == 7
