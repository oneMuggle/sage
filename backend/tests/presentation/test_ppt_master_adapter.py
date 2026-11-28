"""PptMasterAdapter 单元测试 —— 用假技能目录驱动真实子进程，不依赖外部网络。

策略：在 tmp_path 下伪造一个"技能目录"（scripts/attribution_guard.py 等），
让被测适配器用当前解释器真实 subprocess 调用这些一次性脚本，从而覆盖
命令组装、报告解析、超时/缺解释器等分支，而不需要真的安装 ppt-master。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.services import ppt_master_adapter as ppm
from backend.services.ppt_master_adapter import (
    PptMasterAdapter,
    PptMasterEnvError,
    PptMasterRunError,
    _interpret_quality,
)

_PASS_REPORT = {
    "summary": {"total": 1, "passed": 1, "warnings": 1, "errors": 0},
    "categories": {
        "blocking": {"count": 0, "issues": []},
        "introduced": {"count": 1, "issues": [{"code": "W001", "message": "minor"}]},
        "inherited": {"count": 0, "issues": []},
    },
}

_FAIL_REPORT = {
    "summary": {"total": 1, "passed": 0, "warnings": 0, "errors": 2},
    "categories": {
        "blocking": {"count": 2, "issues": [{"code": "E1"}, {"code": "E2"}]},
        "introduced": {"count": 0, "issues": []},
        "inherited": {"count": 0, "issues": []},
    },
}


def _make_skill(
    tmp_path: Path,
    *,
    guard_exit: int = 0,
    report: dict | None = _PASS_REPORT,
    converter_ok: bool = True,
    converter_delay: float = 0.0,
) -> Path:
    root = tmp_path / "skill"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)

    (scripts / "attribution_guard.py").write_text(
        f"import sys\nsys.exit({guard_exit})\n", encoding="utf-8"
    )

    if report is None:
        # 不写报告的检查器（模拟脚本崩溃/未产出）
        checker = "import sys\nsys.exit(0)\n"
    else:
        import json

        payload = json.dumps(report)
        checker = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "proj = Path(sys.argv[1])\n"
            "(proj / 'validation').mkdir(parents=True, exist_ok=True)\n"
            f"(proj / 'validation' / 'svg_quality_report.json').write_text({payload!r}, encoding='utf-8')\n"
        )
    (scripts / "svg_quality_checker.py").write_text(checker, encoding="utf-8")

    converter = "import sys, time\n" "from pathlib import Path\n" f"time.sleep({converter_delay})\n"
    if converter_ok:
        converter += (
            "args = sys.argv[1:]\n"
            "out = Path(args[args.index('-o') + 1])\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_bytes(b'PK\\x03\\x04fake')\n"
        )
    else:
        converter += "sys.exit(2)\n"
    (scripts / "svg_to_pptx.py").write_text(converter, encoding="utf-8")
    return root


def _adapter(root: Path, **kwargs) -> PptMasterAdapter:
    return PptMasterAdapter(skill_root=root, python_executable=sys.executable, **kwargs)


# --------------------------------------------------------------------------- #
# 技能目录解析
# --------------------------------------------------------------------------- #
def test_resolve_skill_root_uses_explicit(tmp_path: Path):
    root = _make_skill(tmp_path)
    assert _adapter(root).skill_root == root.resolve()


def test_resolve_skill_root_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SAGE_PPT_MASTER_ROOT", raising=False)
    monkeypatch.setattr(ppm.Path, "home", classmethod(lambda cls: tmp_path))
    if Path("/opt/agent-skills/ppt-master").exists():
        pytest.skip("/opt/agent-skills/ppt-master 存在，无法构造缺失场景")
    with pytest.raises(PptMasterEnvError):
        PptMasterAdapter(skill_root=None)


# --------------------------------------------------------------------------- #
# 环境 / 完整性
# --------------------------------------------------------------------------- #
def test_check_environment_ok(tmp_path: Path):
    root = _make_skill(tmp_path)
    info = _adapter(root).check_environment()
    assert info["skill_root"] == str(root.resolve())
    assert info["python"] == sys.executable


def test_check_environment_guard_failure(tmp_path: Path):
    root = _make_skill(tmp_path, guard_exit=3)
    with pytest.raises(PptMasterEnvError, match="完整性校验失败"):
        _adapter(root).check_environment()


def test_check_environment_missing_script(tmp_path: Path):
    root = _make_skill(tmp_path)
    (root / "scripts" / "svg_to_pptx.py").unlink()
    with pytest.raises(PptMasterEnvError, match="缺少必需脚本"):
        _adapter(root).check_environment()


# --------------------------------------------------------------------------- #
# 质量门禁
# --------------------------------------------------------------------------- #
def test_quality_check_passed(tmp_path: Path):
    adapter = _adapter(_make_skill(tmp_path))
    project = tmp_path / "proj"
    outcome = adapter.quality_check(project)
    assert outcome.passed is True
    assert outcome.blocking_errors == []
    assert len(outcome.warnings) == 1
    assert outcome.report_path is not None
    assert outcome.report_path.is_file()


def test_quality_check_blocking(tmp_path: Path):
    adapter = _adapter(_make_skill(tmp_path, report=_FAIL_REPORT))
    outcome = adapter.quality_check(tmp_path / "proj")
    assert outcome.passed is False
    assert len(outcome.blocking_errors) == 2


def test_quality_check_missing_report(tmp_path: Path):
    adapter = _adapter(_make_skill(tmp_path, report=None))
    with pytest.raises(PptMasterRunError, match="未产出"):
        adapter.quality_check(tmp_path / "proj")


def test_interpret_quality_falls_back_to_summary_errors(tmp_path: Path):
    report = {"summary": {"errors": 1, "warnings": 0}, "categories": {}}
    outcome = _interpret_quality(report, tmp_path / "r.json")
    assert outcome.passed is False


# --------------------------------------------------------------------------- #
# 转换
# --------------------------------------------------------------------------- #
def test_convert_success(tmp_path: Path):
    adapter = _adapter(_make_skill(tmp_path))
    out = tmp_path / "nested" / "deck.pptx"
    outcome = adapter.convert_to_pptx(tmp_path / "proj", out)
    assert out.is_file()
    assert outcome.output_path == out


def test_convert_failure(tmp_path: Path):
    adapter = _adapter(_make_skill(tmp_path, converter_ok=False))
    out = tmp_path / "deck.pptx"
    with pytest.raises(PptMasterRunError, match="转换失败"):
        adapter.convert_to_pptx(tmp_path / "proj", out)
    assert not out.exists()


# --------------------------------------------------------------------------- #
# 子进程边界
# --------------------------------------------------------------------------- #
def test_run_missing_interpreter(tmp_path: Path):
    root = _make_skill(tmp_path)
    adapter = PptMasterAdapter(skill_root=root, python_executable="/nonexistent/python-xyz")
    with pytest.raises(PptMasterEnvError, match="解释器不可用"):
        adapter.check_environment()


def test_run_timeout(tmp_path: Path):
    adapter = _adapter(_make_skill(tmp_path, converter_delay=5), timeout_s=0.2)
    with pytest.raises(PptMasterRunError, match="超时"):
        adapter.convert_to_pptx(tmp_path / "proj", tmp_path / "deck.pptx")
