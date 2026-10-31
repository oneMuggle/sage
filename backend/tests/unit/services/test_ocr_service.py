"""本地 OCR 服务/引擎单元测试（fake 引擎，不依赖 tesseract/onnxruntime）。"""

from __future__ import annotations

import base64

import pytest

from backend.services.ocr import (
    QUALITY_FAILED,
    OcrConfig,
    OcrLine,
    OcrResult,
    OcrService,
    load_ocr_config,
)
from backend.services.ocr.engines.rapidocr import _parse_result
from backend.services.ocr.engines.tesseract import (
    _lines_from_data,
    resolve_lang_with_fallback,
)

pytestmark = pytest.mark.unit


class FakeEngine:
    """最小引擎桩：记录调用次数，可配置失败/文本。"""

    def __init__(
        self,
        name: str,
        available: bool = True,
        text: str = "识别文本",
        error: str = "",
        quality: str = "ok",
    ) -> None:
        self.name = name
        self._available = available
        self.text = text
        self.error = error
        self.quality = quality
        self.calls = 0

    def available(self):
        return (self._available, "" if self._available else "missing")

    def recognize(self, image_bytes, opts):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return OcrResult(
            text=self.text,
            lines=(OcrLine(text=self.text, confidence=0.9),),
            engine=self.name,
            lang=opts.lang,
            quality=self.quality,
        )


def _service(engines, **config):
    values = {
        "enabled": True,
        "engine": "auto",
        "lang": "auto",
        "prefer_local_for_images": False,
        "min_confidence": 0.4,
        "max_side": 2048,
        "timeout_s": 30.0,
    }
    values.update(config)
    return OcrService(
        engines=engines,
        config_provider=lambda: OcrConfig(**values),
    )


def test_auto_prefers_rapidocr() -> None:
    rapid = FakeEngine("rapidocr", text="rapid")
    tess = FakeEngine("tesseract", text="tess")

    result = _service([rapid, tess]).recognize_bytes(b"fake-image")

    assert result.engine == "rapidocr"
    assert result.text == "rapid"
    assert tess.calls == 0


def test_auto_falls_back_to_tesseract() -> None:
    rapid = FakeEngine("rapidocr", available=False)
    tess = FakeEngine("tesseract", text="tess")

    result = _service([rapid, tess]).recognize_bytes(b"fake-image")

    assert result.engine == "tesseract"
    assert result.text == "tess"


def test_disabled_returns_failure() -> None:
    result = _service([FakeEngine("x")], enabled=False).recognize_bytes(b"img")

    assert result.quality == QUALITY_FAILED
    assert result.error == "ocr_disabled"


def test_too_large_returns_failure() -> None:
    result = _service([FakeEngine("x")]).recognize_bytes(b"x" * (10 * 1024 * 1024 + 1))

    assert result.quality == QUALITY_FAILED
    assert result.error == "image_too_large"


def test_engine_exception_is_folded() -> None:
    result = _service([FakeEngine("x", error="boom")]).recognize_bytes(b"img")

    assert result.quality == QUALITY_FAILED
    assert result.error == "boom"
    assert result.engine == "x"


def test_cache_hit_marks_cached_and_skips_engine() -> None:
    engine = FakeEngine("x")
    service = _service([engine])

    first = service.recognize_bytes(b"same-image")
    second = service.recognize_bytes(b"same-image")

    assert first.cached is False
    assert second.cached is True
    assert engine.calls == 1


def test_data_url_invalid_returns_failure() -> None:
    result = _service([FakeEngine("x")]).recognize_data_url("not-a-data-url")

    assert result.quality == QUALITY_FAILED
    assert result.error == "invalid_image_data_url"


def test_data_url_decodes_and_recognizes() -> None:
    payload = base64.b64encode(b"fake-image").decode("ascii")
    result = _service([FakeEngine("x", text="来自 data URL")]).recognize_data_url(
        "data:image/png;base64," + payload
    )

    assert result.text == "来自 data URL"


def test_capabilities_reports_engine_status() -> None:
    caps = _service(
        [FakeEngine("rapidocr", available=False), FakeEngine("tesseract")]
    ).capabilities()

    assert caps["available"] is True
    assert caps["selected_engine"] == "tesseract"
    assert [item["name"] for item in caps["engines"]] == ["rapidocr", "tesseract"]


def test_rapidocr_parse_object_shape() -> None:
    class Output:
        txts = ["第一行", "低置信度"]
        scores = [0.95, 0.2]
        boxes = [
            [[0, 0], [10, 0], [10, 10], [0, 10]],
            [[0, 20], [10, 20], [10, 30], [0, 30]],
        ]

    lines = _parse_result(Output(), 0.5)

    assert [line.text for line in lines] == ["第一行"]
    assert lines[0].bbox == (0, 0, 10, 10)


def test_rapidocr_parse_legacy_shape() -> None:
    raw = (
        [
            [[[0, 0], [10, 0], [10, 10], [0, 10]], "hello", 0.8],
            [[[0, 20], [10, 20], [10, 30], [0, 30]], "world", 0.3],
        ],
        0.1,
    )

    lines = _parse_result(raw, 0.5)

    assert [line.text for line in lines] == ["hello"]


def test_rapidocr_parse_numpy_shape() -> None:
    """3.x 返回 numpy 数组时不能触发真值歧义。"""
    np = pytest.importorskip("numpy")

    class Output:
        txts = np.array(["第一行", "第二行"])
        scores = np.array([0.95, 0.2])
        boxes = np.array(
            [
                [[0, 0], [10, 0], [10, 10], [0, 10]],
                [[0, 20], [10, 20], [10, 30], [0, 30]],
            ]
        )

    lines = _parse_result(Output(), 0.5)

    assert [line.text for line in lines] == ["第一行"]
    assert lines[0].bbox == (0, 0, 10, 10)


def test_tesseract_lines_filter_low_confidence() -> None:
    data = {
        "text": ["OCR", "噪声", "识别文本"],
        "conf": [95, 10, 88],
        "block_num": [1, 1, 1],
        "par_num": [1, 1, 2],
        "line_num": [1, 1, 1],
        "left": [0, 0, 0],
        "top": [0, 0, 0],
        "width": [10, 10, 10],
        "height": [10, 10, 10],
    }

    lines, best = _lines_from_data(data, 0.4)

    assert [line.text for line in lines] == ["OCR", "识别文本"]
    assert best == pytest.approx(0.95)


def test_resolve_lang_falls_back_to_installed() -> None:
    class FakePytesseract:
        @staticmethod
        def get_languages(config=""):
            return ["chi_sim", "eng"]

    assert resolve_lang_with_fallback(FakePytesseract, "jpn+kor") == "eng"
    assert resolve_lang_with_fallback(FakePytesseract, "eng+jpn") == "eng"
    assert resolve_lang_with_fallback(FakePytesseract, "ch") == "chi_sim+eng"


def test_config_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.ocr.config._read_preference", lambda: {})
    monkeypatch.setenv("SAGE_OCR_LANG", "en")
    monkeypatch.setenv("SAGE_OCR_MIN_CONFIDENCE", "0")

    config = load_ocr_config()

    assert config.lang == "en"
    assert config.min_confidence == 0.0


def test_rapidocr_model_dir_resolution(monkeypatch, tmp_path) -> None:
    from backend.services.ocr.engines.rapidocr import resolve_model_dir

    monkeypatch.setenv("SAGE_OCR_MODEL_DIR", str(tmp_path))
    assert resolve_model_dir() == tmp_path

    monkeypatch.delenv("SAGE_OCR_MODEL_DIR")
    monkeypatch.delenv("SAGE_USER_DATA_DIR", raising=False)
    resolved = resolve_model_dir()
    # 仓库内没有模型目录时必须返回 None（使用包内默认模型），
    # 而不是误判引擎不可用。
    assert resolved is None or resolved.is_dir()
