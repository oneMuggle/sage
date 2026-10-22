"""T-1 镜像布局专项测试。

验证 script_runner 的快照镜像行为：
- 白名单子目录（scripts/references/assets/templates）整体复制到快照
- 非白名单子目录不进入快照
- 脚本的 dirname(__file__) 相对路径能正确找到镜像中的 assets 等资源
- 符号链接不被镜像
- 顶层（非白名单子目录内）脚本仍可执行
- 清理移除整个快照根
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.skills.skill_md.confirm import ConfirmationPort
from backend.skills.skill_md.sandbox import SandboxPort, SandboxResult
from backend.skills.skill_md.script_runner import ScriptRunner
from backend.skills.skill_md.skill import SkillMdDocument

pytestmark = [pytest.mark.unit]


def _make_doc(name: str = "mirror-skill", base_dir: Optional[Path] = None) -> SkillMdDocument:
    return SkillMdDocument(
        name=name,
        description="Mirror layout test skill",
        base_dir=base_dir or Path("/tmp/skills/mirror-skill"),
    )


def _find_snapshot_root(path: Path) -> Path:
    """沿父级向上查找 ``sage-skill-*`` 临时目录。"""
    for ancestor in path.parents:
        if ancestor.name.startswith("sage-skill-"):
            return ancestor
    raise AssertionError(f"no sage-skill-* ancestor found for {path}")


# =====================================================================
# 镜像结构
# =====================================================================


@pytest.mark.asyncio()
async def test_mirror_layout_includes_whitelisted_subdirs(tmp_path):
    """快照镜像布局：白名单子目录整体复制到快照，非白名单子目录被忽略。"""
    for subdir in ("scripts", "assets", "references", "templates"):
        (tmp_path / subdir).mkdir()
    (tmp_path / "scripts" / "scan.py").write_text("print('scan')\n", encoding="utf-8")
    (tmp_path / "assets" / "report.html").write_text("<html></html>\n", encoding="utf-8")
    (tmp_path / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "templates" / "default.txt").write_text("default\n", encoding="utf-8")
    # 非白名单子目录 —— 不应进入快照
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "secret.txt").write_text("secret\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        captured["request"] = request
        captured["snapshot_root"] = _find_snapshot_root(request.script_path)
        captured["snapshot_entries"] = sorted(
            p.name for p in captured["snapshot_root"].iterdir()
        )
        return SandboxResult(True, 0, "ok", "", 1)

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(
        sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path]
    )

    result = await runner.run_script(
        doc=doc, script_name="scripts/scan.py", args=()
    )

    assert result.success is True
    for expected in ("scripts", "assets", "references", "templates"):
        assert expected in captured["snapshot_entries"], (
            f"missing whitelist subdir {expected!r} in snapshot"
        )
    assert "private" not in captured["snapshot_entries"]
    # 脚本路径在快照的 scripts/ 下
    assert captured["request"].script_path.parent.name == "scripts"
    # 执行后清理整个快照根
    assert not captured["snapshot_root"].exists()


@pytest.mark.asyncio()
async def test_mirror_layout_nested_resources_are_mirrored(tmp_path):
    """嵌套资源文件（assets/subdir/foo.html）也应被镜像。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    nested_assets = tmp_path / "assets" / "subdir"
    nested_assets.mkdir(parents=True)
    (scripts_dir / "scan.py").write_text("print('scan')\n", encoding="utf-8")
    (nested_assets / "deep.html").write_text("<deep/>\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        snapshot_root = _find_snapshot_root(request.script_path)
        mirrored_deep = snapshot_root / "assets" / "subdir" / "deep.html"
        # 必须在 cleanup 前读取
        captured["deep_exists"] = mirrored_deep.is_file()
        captured["deep_content"] = (
            mirrored_deep.read_text(encoding="utf-8") if mirrored_deep.is_file() else None
        )
        return SandboxResult(True, 0, "ok", "", 1)

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(
        sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path]
    )

    result = await runner.run_script(doc=doc, script_name="scripts/scan.py", args=())

    assert result.success is True
    assert captured["deep_exists"] is True
    assert captured["deep_content"] == "<deep/>\n"


# =====================================================================
# dirname(__file__) 相对路径（端到端）
# =====================================================================


@pytest.mark.asyncio()
async def test_mirror_layout_script_can_find_sibling_asset_via_relative_path(tmp_path):
    """脚本用 dirname(__file__) / '..' / 'assets' 拼路径能找到镜像中的模板。

    这是 storage-analyzer 的 build_report.py 真实使用模式：
    ``HERE = os.path.dirname(os.path.abspath(__file__))``
    ``TEMPLATE = os.path.join(HERE, '..', 'assets', 'report_template.html')``
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()

    script = scripts_dir / "reader.py"
    script.write_text(
        "import os\n"
        "here = os.path.dirname(os.path.abspath(__file__))\n"
        "asset = os.path.join(here, '..', 'assets', 'template.html')\n"
        "with open(asset) as f:\n"
        "    print(f.read(), end='')\n",
        encoding="utf-8",
    )
    (assets_dir / "template.html").write_text(
        "HELLO_FROM_ASSET\n", encoding="utf-8"
    )

    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        # 真跑脚本验证 dirname(__file__) 解析到镜像内的 scripts/
        proc = subprocess.run(
            [sys.executable, str(request.script_path)],
            cwd=str(request.cwd),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        captured["stdout"] = proc.stdout
        captured["stderr"] = proc.stderr
        captured["returncode"] = proc.returncode
        return SandboxResult(
            success=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_ms=1,
        )

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(
        sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path]
    )

    result = await runner.run_script(
        doc=doc, script_name="scripts/reader.py", args=()
    )

    assert result.success is True, (
        f"script failed: rc={captured.get('returncode')}\n"
        f"stderr={captured.get('stderr')}"
    )
    assert captured["stdout"] == "HELLO_FROM_ASSET\n"


# =====================================================================
# 符号链接 / 安全
# =====================================================================


@pytest.mark.asyncio()
@pytest.mark.skipif(os.name == "nt", reason="symlink test POSIX-only")
async def test_mirror_layout_skips_symlinks_in_resources(tmp_path):
    """白名单资源子目录内的符号链接不应被镜像到快照。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    (scripts_dir / "scan.py").write_text("print('scan')\n", encoding="utf-8")
    real_file = assets_dir / "real.html"
    real_file.write_text("<real/>\n", encoding="utf-8")
    try:
        link = assets_dir / "link.html"
        link.symlink_to(outside / "nope.html")
    except (OSError, NotImplementedError):
        pytest.skip("当前环境无 symlink 特权")

    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        snapshot_root = _find_snapshot_root(request.script_path)
        mirrored_assets = snapshot_root / "assets"
        # 在 cleanup 前检查
        captured["real_exists"] = (mirrored_assets / "real.html").is_file()
        captured["link_exists"] = (mirrored_assets / "link.html").exists()
        return SandboxResult(True, 0, "ok", "", 1)

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(
        sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path]
    )

    result = await runner.run_script(
        doc=doc, script_name="scripts/scan.py", args=()
    )

    assert result.success is True
    assert captured["real_exists"] is True
    # 符号链接不应被镜像（既不是文件也不是断链）
    assert captured["link_exists"] is False


# =====================================================================
# 顶层脚本（不在任何白名单子目录内）
# =====================================================================


@pytest.mark.asyncio()
async def test_mirror_layout_top_level_script_still_executable(tmp_path):
    """脚本在 base_dir 顶层（不在任何白名单子目录）也能执行。"""
    script = tmp_path / "top.py"
    script.write_text("print('top')\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        captured["request"] = request
        captured["snapshot_root"] = _find_snapshot_root(request.script_path)
        return SandboxResult(True, 0, "ok", "", 1)

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(
        sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path]
    )

    result = await runner.run_script(doc=doc, script_name="top.py", args=())

    assert result.success is True
    # 快照脚本在快照根下（无中间子目录）
    assert captured["request"].script_path.parent == captured["snapshot_root"]
    assert captured["request"].script_path.name == "top.py"


# =====================================================================
# 清理完整性
# =====================================================================


@pytest.mark.asyncio()
async def test_mirror_layout_cleanup_removes_whole_tree(tmp_path):
    """执行后快照根（sage-skill-*）整棵被移除，无残留。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "scan.py").write_text("print('scan')\n", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "tpl.html").write_text("<x/>\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        captured["snapshot_root"] = _find_snapshot_root(request.script_path)
        # 确认快照根下有多个子目录（证明清理前确实存在）
        captured["entries_before_cleanup"] = sorted(
            p.name for p in captured["snapshot_root"].iterdir()
        )
        return SandboxResult(True, 0, "ok", "", 1)

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(
        sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path]
    )

    result = await runner.run_script(
        doc=doc, script_name="scripts/scan.py", args=()
    )

    assert result.success is True
    assert "scripts" in captured["entries_before_cleanup"]
    assert "assets" in captured["entries_before_cleanup"]
    # 清理后整个快照根不再存在
    assert not captured["snapshot_root"].exists()


@pytest.mark.asyncio()
async def test_mirror_layout_sandbox_exception_still_cleans_tree(tmp_path):
    """沙箱抛异常时整棵快照也应被清理。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "scan.py").write_text("print('scan')\n", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "tpl.html").write_text("<x/>\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        captured["snapshot_root"] = _find_snapshot_root(request.script_path)
        raise RuntimeError("sandbox crashed")

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(
        sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path]
    )

    result = await runner.run_script(
        doc=doc, script_name="scripts/scan.py", args=()
    )

    assert result.success is False
    assert not captured["snapshot_root"].exists()


# =====================================================================
# POSIX 权限
# =====================================================================


@pytest.mark.asyncio()
@pytest.mark.skipif(os.name != "posix", reason="POSIX-only permission model")
async def test_mirror_layout_posix_permissions(tmp_path):
    """POSIX：快照根、镜像子目录、快照脚本权限分别为 0700 / 0700 / 0600。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "scan.py").write_text("print('scan')\n", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "tpl.html").write_text("<x/>\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        snapshot_root = _find_snapshot_root(request.script_path)
        scripts_mirror = snapshot_root / "scripts"
        # 在 cleanup 前检查权限
        captured["root_mode"] = stat.S_IMODE(snapshot_root.stat().st_mode)
        captured["scripts_mode"] = stat.S_IMODE(scripts_mirror.stat().st_mode)
        captured["script_mode"] = stat.S_IMODE(request.script_path.stat().st_mode)
        return SandboxResult(True, 0, "ok", "", 1)

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(
        sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path]
    )

    result = await runner.run_script(
        doc=doc, script_name="scripts/scan.py", args=()
    )

    assert result.success is True
    assert captured["root_mode"] == 0o700, "snapshot root should be 0700"
    assert captured["scripts_mode"] == 0o700, "mirrored scripts/ subdir should be 0700"
    assert captured["script_mode"] == 0o600, "snapshot script should be 0600"
