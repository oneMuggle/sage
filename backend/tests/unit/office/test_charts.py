"""Unit tests for :mod:`backend.office.charts` (批次 2.1).

Covers:
- render_chart_png: line/bar/hbar/pie 全类型出图、PNG 魔数、CJK 标题、
  输出目录自动创建、未知类型 / 数据长度不一致报 OfficeGenerateError
- decode_image_base64: 裸 base64 / data URI、超限拒绝、非法编码拒绝
- resolve_image_payload: data URI 直通、绝对路径、search_dirs 相对路径、
  未命中报错
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from backend.office.charts import (
    MAX_IMAGE_BYTES,
    decode_image_base64,
    render_chart_png,
    resolve_image_payload,
)
from backend.office.errors import OfficeGenerateError
from backend.office.models import ChartSeriesSpec, ChartSpec

pytestmark = pytest.mark.unit

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: 1x1 red PNG（与 conftest/test_ppt 的 helper 同源）。
_MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP8z8Dw"
    "HwAFBQIAX8v0gQAAAABJRU5ErkJggg=="
)


def _make_minimal_png(path: Path) -> Path:
    path.write_bytes(base64.b64decode(_MINIMAL_PNG_B64, validate=True))
    return path


def _line_spec(**overrides) -> ChartSpec:
    data = {
        "type": "line",
        "title": "季度销售趋势",
        "series": [
            ChartSeriesSpec(name="系列A", x=["Q1", "Q2", "Q3"], y=[10, 20, 30]),
            ChartSeriesSpec(name="系列B", x=["Q1", "Q2", "Q3"], y=[5, 15, 25]),
        ],
    }
    data.update(overrides)
    return ChartSpec(**data)


def _require_matplotlib() -> None:
    pytest.importorskip("matplotlib", reason="matplotlib 未安装（main 通道可选依赖）")


# ──────────────────────────────────────────────────────────────────────
# render_chart_png
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("chart_type", ["line", "bar", "hbar", "pie"])
def test_render_chart_png_produced_for_all_types(tmp_path: Path, chart_type: str) -> None:
    _require_matplotlib()
    spec = ChartSpec(
        type=chart_type,
        title="图 title",
        labels=["一月", "二月", "三月"],
        series=[ChartSeriesSpec(name="销量", y=[3, 1, 4])],
    )
    out = render_chart_png(spec, tmp_path)
    assert out.parent == tmp_path
    assert out.suffix == ".png"
    assert out.is_file()
    assert out.read_bytes()[:8] == _PNG_MAGIC
    assert out.stat().st_size > 0


def test_render_cjk_title_produces_png(tmp_path: Path) -> None:
    """中文标题（默认字体无 CJK 字形会变豆腐块）也必须成功出图。"""
    _require_matplotlib()
    out = render_chart_png(_line_spec(), tmp_path)
    assert out.is_file()
    assert out.read_bytes()[:8] == _PNG_MAGIC


def test_render_creates_missing_output_dir(tmp_path: Path) -> None:
    _require_matplotlib()
    target = tmp_path / "nested" / "charts"
    out = render_chart_png(_line_spec(), target)
    assert out.is_file()
    assert out.parent == target


def test_render_unknown_type_raises_office_generate_error(tmp_path: Path) -> None:
    """model_construct 绕过 Pydantic Literal 校验时，render 仍运行时守卫。"""
    bad = ChartSpec.model_construct(
        type="scatter",
        title=None,
        labels=None,
        series=[ChartSeriesSpec(name="s", y=[1])],
    )
    with pytest.raises(OfficeGenerateError) as excinfo:
        render_chart_png(bad, tmp_path)
    assert "不支持的图表类型" in str(excinfo.value)


def test_render_pydantic_rejects_unknown_type() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChartSpec(type="scatter", series=[ChartSeriesSpec(name="s", y=[1])])


def test_render_length_mismatch_raises(tmp_path: Path) -> None:
    with pytest.raises(OfficeGenerateError):
        render_chart_png(
            ChartSpec(
                type="bar",
                labels=["一月", "二月"],
                series=[ChartSeriesSpec(name="销量", y=[1, 2, 3])],
            ),
            tmp_path,
        )


def test_render_xy_length_mismatch_raises(tmp_path: Path) -> None:
    with pytest.raises(OfficeGenerateError):
        render_chart_png(
            ChartSpec(
                type="line",
                series=[ChartSeriesSpec(name="s", x=["a", "b"], y=[1, 2, 3])],
            ),
            tmp_path,
        )


# ──────────────────────────────────────────────────────────────────────
# decode_image_base64 / resolve_image_payload
# ──────────────────────────────────────────────────────────────────────


def test_decode_image_base64_accepts_raw_and_data_uri() -> None:
    raw = decode_image_base64(_MINIMAL_PNG_B64)
    assert raw == base64.b64decode(_MINIMAL_PNG_B64)
    uri = "data:image/png;base64," + _MINIMAL_PNG_B64
    assert decode_image_base64(uri) == raw


def test_decode_image_base64_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid_image_data"):
        decode_image_base64("not base64 !!!")


def test_decode_image_base64_rejects_oversize() -> None:
    big = base64.b64encode(b"x" * (MAX_IMAGE_BYTES + 1)).decode()
    with pytest.raises(ValueError, match="image_too_large"):
        decode_image_base64(big)


def test_resolve_image_payload_via_data_uri(tmp_path: Path) -> None:
    uri = "data:image/png;base64," + _MINIMAL_PNG_B64
    assert resolve_image_payload(uri) == base64.b64decode(_MINIMAL_PNG_B64)


def test_resolve_image_payload_absolute_path(tmp_path: Path) -> None:
    png = _make_minimal_png(tmp_path / "pic.png")
    assert resolve_image_payload(str(png)) == png.read_bytes()


def test_resolve_image_payload_relative_via_search_dirs(tmp_path: Path) -> None:
    png = _make_minimal_png(tmp_path / "pic.png")
    result = resolve_image_payload("pic.png", search_dirs=[tmp_path])
    assert result == png.read_bytes()


def test_resolve_image_payload_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="image_file_not_found"):
        resolve_image_payload("nope.png", search_dirs=[tmp_path])
