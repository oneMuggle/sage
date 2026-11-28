"""PresentationService — 把一组 SVG 幻灯片编排成原生可编辑 PPTX。

编排流程（全部走 ppt-master 的确定性工程层，不含 AI 创作）：

    入参 SVG 列表
        -> 组装临时 ppt-master 项目（<work>/proj/svg_output/NN.svg）
        -> PptMasterAdapter.quality_check（最终质量门禁，必须通过）
        -> PptMasterAdapter.convert_to_pptx（SVG -> DrawingML，原生可编辑）
        -> 产物复制到目标目录，返回质量摘要

质量门禁不通过时**不转换**，直接返回失败结果与阻塞问题，让调用方修复后重试——
这与 ppt-master 的 "blocking 即停" 纪律一致。

也支持直接转换一份已有的 ppt-master 项目目录（render_project）。
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from backend.services.ppt_master_adapter import (
    ConversionOutcome,
    PptMasterAdapter,
    PptMasterEnvError,
    PptMasterRunError,
    QualityOutcome,
)

__all__ = [
    "PresentationService",
    "RenderResult",
    "PresentationInputError",
]

_MAX_SLIDES = 200
_MAX_SLIDE_BYTES = 5 * 1024 * 1024


class PresentationInputError(ValueError):
    """调用方入参非法（幻灯片数量/大小/文件名越界）。"""


@dataclass
class RenderResult:
    """一次渲染的结果。"""

    success: bool
    output_path: Optional[Path] = None
    quality_passed: bool = False
    blocking_errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    message: str = ""


class PresentationService:
    """SVG -> PPTX 编排服务（依赖可注入的 PptMasterAdapter）。"""

    def __init__(self, adapter: Optional[PptMasterAdapter] = None) -> None:
        self._adapter = adapter

    @property
    def adapter(self) -> PptMasterAdapter:
        if self._adapter is None:
            self._adapter = PptMasterAdapter()
        return self._adapter

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #
    def render_from_svgs(
        self,
        svg_slides: Sequence[str],
        output_path: Path,
    ) -> RenderResult:
        """把一组 SVG 字符串（按顺序，每项一页）渲染成一份 PPTX。"""
        _validate_svgs(svg_slides)
        output_path = _safe_output_path(output_path)

        work_root = Path(tempfile.mkdtemp(prefix="sage-pptm-"))
        try:
            project_dir = work_root / "proj"
            svg_dir = project_dir / "svg_output"
            svg_dir.mkdir(parents=True, exist_ok=True)
            for idx, svg in enumerate(svg_slides, start=1):
                (svg_dir / f"{idx:02d}.svg").write_text(svg, encoding="utf-8")

            return self._render_project_core(project_dir, output_path)
        finally:
            shutil.rmtree(work_root, ignore_errors=True)

    def render_project(self, project_dir: Path, output_path: Path) -> RenderResult:
        """转换一份已有的 ppt-master 项目目录（含 svg_output/*.svg）。"""
        project_dir = Path(project_dir)
        if not (project_dir / "svg_output").is_dir():
            raise PresentationInputError(f"项目目录缺少 svg_output/：{project_dir}")
        output_path = _safe_output_path(output_path)
        return self._render_project_core(project_dir, output_path)

    def check_environment(self) -> dict:
        """透传适配器的环境/完整性检查（含 guard）。"""
        return self.adapter.check_environment()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _render_project_core(self, project_dir: Path, output_path: Path) -> RenderResult:
        try:
            quality: QualityOutcome = self.adapter.quality_check(project_dir)
        except (PptMasterEnvError, PptMasterRunError) as exc:
            return RenderResult(success=False, message=str(exc))

        if not quality.passed:
            return RenderResult(
                success=False,
                quality_passed=False,
                blocking_errors=quality.blocking_errors,
                warnings=quality.warnings,
                summary=quality.summary,
                message=(
                    f"质量门禁未通过：{len(quality.blocking_errors)} 个阻塞问题，" "已中止转换"
                ),
            )

        try:
            conversion: ConversionOutcome = self.adapter.convert_to_pptx(project_dir, output_path)
        except (PptMasterEnvError, PptMasterRunError) as exc:
            return RenderResult(
                success=False,
                quality_passed=True,
                blocking_errors=quality.blocking_errors,
                warnings=quality.warnings,
                summary=quality.summary,
                message=str(exc),
            )

        return RenderResult(
            success=True,
            output_path=conversion.output_path,
            quality_passed=True,
            blocking_errors=quality.blocking_errors,
            warnings=quality.warnings,
            summary=quality.summary,
            message="生成成功",
        )


def _validate_svgs(svg_slides: Sequence[str]) -> None:
    if not svg_slides:
        raise PresentationInputError("至少需要一页 SVG")
    if len(svg_slides) > _MAX_SLIDES:
        raise PresentationInputError(f"页数超限（>{_MAX_SLIDES}）")
    for idx, svg in enumerate(svg_slides, start=1):
        if not isinstance(svg, str) or not svg.strip():
            raise PresentationInputError(f"第 {idx} 页 SVG 为空或非字符串")
        if len(svg.encode("utf-8")) > _MAX_SLIDE_BYTES:
            raise PresentationInputError(f"第 {idx} 页 SVG 超过 {_MAX_SLIDE_BYTES} 字节")


def _safe_output_path(output_path: Path) -> Path:
    output_path = Path(output_path)
    name = output_path.name
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise PresentationInputError("输出文件名非法")
    if not name.lower().endswith(".pptx"):
        raise PresentationInputError("输出文件必须以 .pptx 结尾")
    return output_path
