"""真实端到端冒烟：调用官方 ppt-master 技能，把 1 页 SVG 转成原生可编辑 PPTX。

仅在机器上存在完整技能目录（含 scripts/attribution_guard.py）时运行，
否则跳过——CI 无此目录，自动 skip。可用 SAGE_PPT_MASTER_ROOT 指定。
"""

from __future__ import annotations

import os
<<<<<<< HEAD
import sys
=======
>>>>>>> origin/main
import zipfile
from pathlib import Path

import pytest

from backend.services.ppt_master_adapter import PptMasterAdapter
from backend.services.presentation_service import PresentationService

pytestmark = pytest.mark.integration

_SKILL_ROOT = Path(
    os.environ.get(
        "SAGE_PPT_MASTER_ROOT",
        str(Path.home() / "project" / "ppt-master" / "skills" / "ppt-master"),
    )
)

_MINIMAL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
    'viewBox="0 0 1280 720" role="img" aria-label="smoke">'
    '<rect x="0" y="0" width="1280" height="720" fill="#FFFFFF"/>'
    '<text x="640" y="360" font-family="Arial" font-size="48" '
    'text-anchor="middle" fill="#222222">Sage PPT Smoke</text>'
    "</svg>"
)


@pytest.mark.skipif(
    not (_SKILL_ROOT / "scripts" / "attribution_guard.py").is_file(),
    reason=f"ppt-master 技能目录不存在：{_SKILL_ROOT}",
)
<<<<<<< HEAD
@pytest.mark.skipif(
    sys.version_info < (3, 9) and not os.environ.get("SAGE_PPT_MASTER_PYTHON"),
    reason="技能脚本要求 Python >= 3.9；请设置 SAGE_PPT_MASTER_PYTHON 指向兼容解释器",
)
=======
>>>>>>> origin/main
def test_render_one_svg_to_pptx(tmp_path: Path):
    adapter = PptMasterAdapter(skill_root=_SKILL_ROOT)
    assert adapter.check_environment()["skill_root"] == str(_SKILL_ROOT.resolve())

    out = tmp_path / "smoke.pptx"
    result = PresentationService(adapter).render_from_svgs([_MINIMAL_SVG], out)

    assert result.success is True, result.message
    assert result.quality_passed is True
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "ppt/presentation.xml" in names
