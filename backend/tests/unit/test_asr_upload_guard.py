"""R22-D8: ASR 上传收紧单元测试

speech_to_text 之前是 READ 级（自动放行）+ 任意文件全量读字节上传云端
—— 提示注入链可把盘上任意文件零审批送出网。收紧后：仅允许音频扩展名
且 ≤25MB；超限/非音频在 build_request 即拒绝（不出网）。
"""

from __future__ import annotations

import pytest

from backend.services.multimodal.asr import ASRCapability
from backend.services.multimodal.capability import CapabilityConfig

pytestmark = pytest.mark.unit


def _config() -> CapabilityConfig:
    return CapabilityConfig(base_url="http://asr.example.com", api_key="k", model="whisper-1")


def test_rejects_non_audio_extension(tmp_path):
    evil = tmp_path / "secrets.txt"
    evil.write_bytes(b"x" * 16)
    with pytest.raises(ValueError, match="不支持的音频扩展名"):
        ASRCapability().build_request(_config(), file_path=str(evil))


def test_rejects_oversized_audio(tmp_path):
    big = tmp_path / "big.wav"
    big.write_bytes(b"\0" * (ASRCapability.MAX_UPLOAD_BYTES + 1))
    with pytest.raises(ValueError, match="上限"):
        ASRCapability().build_request(_config(), file_path=str(big))


def test_accepts_wav_within_limit(tmp_path):
    wav = tmp_path / "ok.wav"
    wav.write_bytes(b"\0" * 64)
    request = ASRCapability().build_request(_config(), file_path=str(wav))
    assert request is not None


def test_rejects_oversized_inline_content():
    with pytest.raises(ValueError, match="上限"):
        ASRCapability().build_request(
            _config(), file_content=b"\0" * (ASRCapability.MAX_UPLOAD_BYTES + 1)
        )
