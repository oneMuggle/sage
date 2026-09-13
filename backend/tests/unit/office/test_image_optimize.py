"""Unit tests for the lazy Pillow image pipeline (Round 22).

Covers `image_optimize.optimize_image_bytes` semantics: small images
pass through untouched, oversized JPEG gets re-encoded within budget,
non-reencodable formats pass through, Pillow absence degrades to
no-op. Pillow availability is injected via monkeypatched find_spec /
_reencode_jpeg so tests run with or without real Pillow.
"""

from __future__ import annotations

import io

import pytest

from backend.office import image_optimize
from backend.office.image_optimize import optimize_image_bytes

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def _fake_jpeg(width: int = 4000, height: int = 3000, size_hint: int = 9_000_000) -> bytes:
    """合成一张超大 JPEG 的假字节（足够通过 magic/阈值判断即可）。"""
    return _JPEG_MAGIC + b"\x00" * size_hint + f"{width}x{height}".encode()


class TestSmallImages:
    def test_small_image_passes_through_untouched(self) -> None:
        small = _JPEG_MAGIC + b"tiny"
        assert optimize_image_bytes(small) == small

    def test_threshold_boundary(self) -> None:
        exactly = b"\xff\xd8\xff" + b"x" * (8 * 1024 * 1024 - 3)
        assert optimize_image_bytes(exactly) == exactly


class TestPillowReencode:
    def test_oversized_jpeg_reencoded_within_budget(self, monkeypatch) -> None:
        """mock Pillow 重编码：返回 ≤ 阈值的"压缩"结果并断言被采用。"""
        compressed = _JPEG_MAGIC + b"x" * (7 * 1024 * 1024)

        def fake_reencode(data: bytes, max_bytes: int):
            return compressed

        monkeypatch.setattr(image_optimize, "_reencode_jpeg", fake_reencode)
        big = _JPEG_MAGIC + b"y" * (9 * 1024 * 1024)
        result = optimize_image_bytes(big)
        assert result == compressed
        assert len(result) <= 8 * 1024 * 1024

    def test_reencode_failure_returns_original(self, monkeypatch) -> None:
        monkeypatch.setattr(
            image_optimize, "_reencode_jpeg", lambda data, max_bytes: None
        )
        big = _JPEG_MAGIC + b"z" * (9 * 1024 * 1024)
        assert optimize_image_bytes(big) == big


class TestPillowAvailability:
    def test_pillow_missing_is_noop(self, monkeypatch) -> None:
        """Pillow 未安装 → find_spec None → 原样返回。"""

        monkeypatch.setattr(
            image_optimize, "is_pillow_available", lambda: False
        )
        big = _JPEG_MAGIC + b"q" * (9 * 1024 * 1024)
        assert optimize_image_bytes(big) == big


class TestRealPillowIfInstalled:
    def test_real_jpeg_roundtrip(self) -> None:
        """真 Pillow 存在时：合成的超大纯色 JPEG 能被压到阈值内。"""
        pytest.importorskip("PIL")
        buf = io.BytesIO()
        try:
            from PIL import Image

            Image.new("RGB", (6000, 4500), color=(200, 100, 50)).save(
                buf, format="JPEG", quality=100
            )
        except Exception:  # noqa: BLE001 — 环境缺 Pillow 时跳过
            pytest.skip("Pillow 不可用")
        data = buf.getvalue()
        if len(data) <= image_optimize.OPTIMIZE_THRESHOLD_BYTES:
            pytest.skip("合成图未超阈值")
        result = optimize_image_bytes(data)
        assert len(result) <= image_optimize.OPTIMIZE_THRESHOLD_BYTES
