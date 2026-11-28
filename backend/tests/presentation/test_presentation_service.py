"""PresentationService 编排逻辑测试（用假适配器，不调用真实子进程）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.ppt_master_adapter import (
    ConversionOutcome,
    PptMasterEnvError,
    PptMasterRunError,
    QualityOutcome,
)
from backend.services.presentation_service import (
    PresentationInputError,
    PresentationService,
    _safe_output_path,
    _validate_svgs,
)


class FakeAdapter:
    """记录调用次数并模拟质量/转换结果的替身。"""

    def __init__(
        self,
        quality: QualityOutcome | None = None,
        convert_error: Exception | None = None,
        quality_error: Exception | None = None,
    ) -> None:
        self._quality = quality or _passed_quality()
        self._convert_error = convert_error
        self._quality_error = quality_error
        self.quality_calls: list[Path] = []
        self.convert_calls: list[tuple[Path, Path]] = []
        self.seen_svgs: list[str] = []

    def quality_check(self, project_dir: Path) -> QualityOutcome:
        if self._quality_error is not None:
            raise self._quality_error
        project_dir = Path(project_dir)
        self.quality_calls.append(project_dir)
        self.seen_svgs = sorted(p.name for p in (project_dir / "svg_output").glob("*.svg"))
        return self._quality

    def convert_to_pptx(self, project_dir: Path, output_path: Path) -> ConversionOutcome:
        if self._convert_error is not None:
            raise self._convert_error
        output_path = Path(output_path)
        self.convert_calls.append((Path(project_dir), output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"PK\\x03\\x04fake")
        return ConversionOutcome(output_path=output_path, postflight_report_path=None, stdout="")


def _passed_quality() -> QualityOutcome:
    return QualityOutcome(
        passed=True,
        blocking_errors=[],
        warnings=[{"code": "W1"}],
        summary={"total": 1, "passed": 1},
        report_path=Path("/tmp/report.json"),
    )


def _blocked_quality() -> QualityOutcome:
    return QualityOutcome(
        passed=False,
        blocking_errors=[{"code": "E1"}, {"code": "E2"}],
        warnings=[],
        summary={"total": 1, "passed": 0, "errors": 2},
        report_path=Path("/tmp/report.json"),
    )


# --------------------------------------------------------------------------- #
# render_from_svgs
# --------------------------------------------------------------------------- #
def test_render_from_svgs_success(tmp_path: Path):
    adapter = FakeAdapter()
    out = tmp_path / "deck.pptx"
    result = PresentationService(adapter).render_from_svgs(["<svg>1</svg>", "<svg>2</svg>"], out)

    assert result.success is True
    assert result.output_path == out
    assert adapter.seen_svgs == ["01.svg", "02.svg"]
    # 临时项目目录在返回前已清理
    assert not adapter.quality_calls[0].exists()


def test_render_from_svgs_blocks_on_quality_failure(tmp_path: Path):
    adapter = FakeAdapter(quality=_blocked_quality())
    result = PresentationService(adapter).render_from_svgs(["<svg/>"], tmp_path / "deck.pptx")

    assert result.success is False
    assert result.quality_passed is False
    assert len(result.blocking_errors) == 2
    assert adapter.convert_calls == []  # 门禁未过 -> 不转换
    assert "中止" in result.message


def test_render_from_svgs_convert_error(tmp_path: Path):
    adapter = FakeAdapter(convert_error=PptMasterRunError("boom"))
    result = PresentationService(adapter).render_from_svgs(["<svg/>"], tmp_path / "deck.pptx")

    assert result.success is False
    assert result.quality_passed is True
    assert result.message == "boom"


def test_render_from_svgs_quality_env_error(tmp_path: Path):
    adapter = FakeAdapter(quality_error=PptMasterEnvError("no skill"))
    result = PresentationService(adapter).render_from_svgs(["<svg/>"], tmp_path / "deck.pptx")

    assert result.success is False
    assert result.message == "no skill"


# --------------------------------------------------------------------------- #
# render_project
# --------------------------------------------------------------------------- #
def test_render_project_requires_svg_output(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    with pytest.raises(PresentationInputError, match="svg_output"):
        PresentationService(FakeAdapter()).render_project(project, tmp_path / "deck.pptx")


def test_render_project_success(tmp_path: Path):
    project = tmp_path / "proj"
    (project / "svg_output").mkdir(parents=True)
    (project / "svg_output" / "01.svg").write_text("<svg/>", encoding="utf-8")
    out = tmp_path / "deck.pptx"
    result = PresentationService(FakeAdapter()).render_project(project, out)
    assert result.success is True
    assert out.is_file()


# --------------------------------------------------------------------------- #
# 入参校验
# --------------------------------------------------------------------------- #
def test_validate_svgs_empty():
    with pytest.raises(PresentationInputError, match="至少"):
        _validate_svgs([])


def test_validate_svgs_too_many():
    with pytest.raises(PresentationInputError, match="页数超限"):
        _validate_svgs(["<svg/>"] * 201)


def test_validate_svgs_blank_item():
    with pytest.raises(PresentationInputError, match="第 2 页"):
        _validate_svgs(["<svg/>", "   "])


def test_validate_svgs_oversized():
    big = "x" * (5 * 1024 * 1024 + 1)
    with pytest.raises(PresentationInputError, match="超过"):
        _validate_svgs([big])


def test_safe_output_path_accepts_absolute_pptx(tmp_path: Path):
    out = tmp_path / "sub" / "deck.pptx"
    assert _safe_output_path(out) == out


def test_safe_output_path_rejects_non_pptx(tmp_path: Path):
    with pytest.raises(PresentationInputError, match=".pptx"):
        _safe_output_path(tmp_path / "deck.txt")


def test_safe_output_path_rejects_backslash_name():
    # 跨平台：文件名含反斜杠一律拒绝（不受 str(绝对路径) 在 Windows 上
    # 天然带反斜杠影响——旧实现会误杀所有 Windows 绝对路径）。
    with pytest.raises(PresentationInputError, match="非法"):
        _safe_output_path(Path("evil\\name.pptx"))
