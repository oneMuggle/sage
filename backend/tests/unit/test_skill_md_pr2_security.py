"""PR-2 脚本执行接线与安全边界测试。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.adapters.out.skill.inproc import InprocSkillAdapter
from backend.adapters.out.skill_script.cli_confirmation import (
    ConfiguredScriptConfirmationAdapter,
)
from backend.adapters.out.skill_script.subprocess_sandbox import SubprocessSandboxAdapter
from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.confirm import ConfirmationPort
from backend.skills.skill_md.importer import SkillMdImporter
from backend.skills.skill_md.loader import SkillMdHotLoader
from backend.skills.skill_md.sandbox import SandboxPort, SandboxRequest
from backend.skills.skill_md.script_runner import ScriptRunner
from backend.skills.skill_md.skill import SkillMdDocument
from backend.skills.skill_md.slash_registry import SlashCommandRegistry

pytestmark = pytest.mark.unit


def _write_skill(root: Path, name: str = "demo") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: demo\n---\nbody\n",
        encoding="utf-8",
    )
    return path


def test_importer_preserves_production_script_runner():
    runner = MagicMock(spec=ScriptRunner)
    importer = SkillMdImporter(SkillRegistry(), script_runner=runner)
    importer._hot_reload_from_path = MagicMock()
    assert importer._script_runner is runner
def test_loader_passes_script_runner_to_skill(tmp_path):
    runner = MagicMock(spec=ScriptRunner)
    registry = SkillRegistry()
    _write_skill(tmp_path)

    loaded, skipped = SkillMdHotLoader(
        registry, dirs=[tmp_path], script_runner=runner
    ).scan_and_load()

    assert (loaded, skipped) == (1, 0)
    assert registry.get("demo")._script_runner is runner


@pytest.mark.asyncio()
async def test_inproc_prefers_execute_v2_and_keeps_sync_fallback():
    registry = SkillRegistry()
    skill = MagicMock()
    skill.name = "demo"
    skill.execute_v2 = AsyncMock(
        return_value=MagicMock(success=True, content="script", metadata={}, error=None)
    )
    registry.register(skill)
    adapter = InprocSkillAdapter.__new__(InprocSkillAdapter)
    adapter._registry = registry
    adapter._enabled = {}
    adapter._usage_count = {}
    adapter._archived = set()

    result = await adapter.execute("demo", "", {"script": "run.py"})

    assert result.success is True
    assert result.content == "script"
    skill.execute_v2.assert_awaited_once_with(params={"script": "run.py"}, context={})
    skill.execute.assert_not_called()


def test_production_adapter_builds_fail_closed_script_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    with patch("backend.skills.register_skill_md_skills") as register:
        adapter = InprocSkillAdapter(registry=SkillRegistry())

    runner = register.call_args.kwargs["script_runner"]
    assert isinstance(runner, ScriptRunner)
    assert isinstance(runner._sandbox, SubprocessSandboxAdapter)
    assert runner._allowed_roots == [tmp_path]
    assert asyncio.run(runner._confirmer.confirm("demo", tmp_path / "x.py", ())) is False
    assert adapter._script_runner is runner


def test_production_script_confirmation_allows_explicit_skill_name(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGE_SKILL_SCRIPT_ALLOWLIST", "skill:demo")
    confirmer = ConfiguredScriptConfirmationAdapter.from_environment()

    assert asyncio.run(confirmer.confirm("demo", tmp_path / "run.py", ())) is True
    assert asyncio.run(confirmer.confirm("other", tmp_path / "run.py", ())) is False


def test_production_script_confirmation_allows_explicit_path_only(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("SAGE_SKILL_SCRIPT_ALLOWLIST", f"path:{allowed}")
    confirmer = ConfiguredScriptConfirmationAdapter.from_environment()

    assert asyncio.run(confirmer.confirm("demo", allowed / "run.py", ())) is True
    assert asyncio.run(confirmer.confirm("demo", tmp_path / "allowed-other.py", ())) is False


def test_production_script_confirmation_ignores_malformed_allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGE_SKILL_SCRIPT_ALLOWLIST", "*,path:relative,unknown:value")
    confirmer = ConfiguredScriptConfirmationAdapter.from_environment()

    assert asyncio.run(confirmer.confirm("demo", tmp_path / "run.py", ())) is False


def test_production_adapter_injects_configured_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path))
    monkeypatch.setenv("SAGE_SKILL_SCRIPT_ALLOWLIST", "skill:demo")
    with patch("backend.skills.register_skill_md_skills") as register:
        adapter = InprocSkillAdapter(registry=SkillRegistry())

    confirmer = adapter._script_runner._confirmer
    assert isinstance(confirmer, ConfiguredScriptConfirmationAdapter)
    assert asyncio.run(confirmer.confirm("demo", tmp_path / "run.py", ())) is True
    assert asyncio.run(confirmer.confirm("not-approved", tmp_path / "run.py", ())) is False
    assert register.call_args.kwargs["script_runner"] is adapter._script_runner


def test_inproc_rescan_discovers_new_roots_and_updates_runner(tmp_path):
    """重扫必须发现初始化后出现的根目录，并同步脚本执行安全边界。"""
    old_root = tmp_path / "old-skills"
    new_root = tmp_path / "new-skills"
    old_root.mkdir()
    new_root.mkdir()
    _write_skill(new_root, "new-skill")

    adapter = InprocSkillAdapter.__new__(InprocSkillAdapter)
    adapter._registry = SkillRegistry()
    adapter._skill_importer = object()
    adapter._script_runner = MagicMock()
    adapter._script_runner._allowed_roots = [old_root]
    adapter._skill_dirs = [old_root]

    with patch(
        "backend.skills.skill_md.loader.discover_skill_md_dirs",
        return_value=[old_root, new_root],
    ) as discover:
        result = adapter.rescan_skill_mds()

    discover.assert_called_once_with()
    assert adapter._skill_dirs == [old_root, new_root]
    assert adapter._script_runner._allowed_roots == [old_root, new_root]
    assert result["total_loaded"] == 1
    assert result["loaded"] == [
        {
            "name": "new-skill",
            "source": "skillmd",
            "path": ".",
        }
    ]



def test_inproc_rescan_rebuilds_slash_registry(tmp_path):
    """重扫加载 user-invocable 技能后，slash 索引必须包含新命令。"""
    root = tmp_path / "skills"
    root.mkdir()
    path = root / "deploy" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(
        "---\nname: deploy\ndescription: deploy\nuser-invocable: true\n---\nbody\n",
        encoding="utf-8",
    )
    adapter = InprocSkillAdapter.__new__(InprocSkillAdapter)
    adapter._registry = SkillRegistry()
    adapter._skill_importer = object()
    adapter._script_runner = None
    adapter._skill_dirs = []
    adapter._enabled = {}
    adapter._archived = set()

    from backend.skills.skill_md.slash_registry import SlashCommandRegistry

    adapter._slash_registry = SlashCommandRegistry.from_registry(adapter._registry)
    adapter._archived = set()

    with patch(
        "backend.skills.skill_md.loader.discover_skill_md_dirs", return_value=[root]
    ):
        result = adapter.rescan_skill_mds()

    assert result["total_loaded"] == 1
    assert "/deploy" in adapter.list_slash_commands()


def test_inproc_delete_removes_slash_command(tmp_path, monkeypatch):
    """删除 user-invocable 技能后，slash 索引不得残留命令。"""
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path))
    skill_dir = tmp_path / "deploy"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: deploy\nuser-invocable: true\n---\nbody\n",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    assert loader.scan_and_load() == (1, 0)

    adapter = InprocSkillAdapter.__new__(InprocSkillAdapter)
    adapter._registry = registry
    adapter._skill_importer = object()
    adapter._slash_registry = SlashCommandRegistry.from_registry(registry)
    adapter._archived = set()

    result = adapter.delete_skill_md("deploy")

    assert result["deleted"] is True
    assert "/deploy" not in adapter.list_slash_commands()
    assert not adapter._registry.exists("deploy")


@pytest.mark.asyncio()
async def test_inproc_import_rebuilds_slash_registry(tmp_path):
    """导入 user-invocable 技能后，slash 索引必须立即刷新。"""
    from io import BytesIO

    adapter = InprocSkillAdapter.__new__(InprocSkillAdapter)
    adapter._registry = SkillRegistry()
    adapter._script_runner = None
    adapter._skill_dirs = []
    adapter._enabled = {}

    adapter._slash_registry = SlashCommandRegistry.from_registry(adapter._registry)
    adapter._archived = set()
    adapter._skill_importer = SkillMdImporter(adapter._registry, skills_dir=tmp_path)

    upload = MagicMock(filename="deploy.md")
    upload.read = AsyncMock(
        side_effect=[
            BytesIO(
                b"---\nname: deploy\ndescription: deploy\nuser-invocable: true\n---\nbody\n"
            ).read(),
            b"",
        ]
    )
    result = await adapter.import_skill_mds([upload])

    assert result["imported"]
    assert adapter.list_slash_commands() == ["/deploy"]


@pytest.mark.asyncio()
async def test_script_runner_rejects_replacement_after_confirmation(tmp_path):
    """确认后脚本被替换时，必须 fail-closed。"""
    script = tmp_path / "run.py"
    script.write_text("print('ok')", encoding="utf-8")
    doc = SkillMdDocument(name="demo", description="demo", base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()
    confirmer = MagicMock(spec=ConfirmationPort)

    async def approve_then_replace(**_kwargs):
        script.unlink()
        outside = tmp_path.parent / "outside.py"
        outside.write_text("print('ok')", encoding="utf-8")
        script.symlink_to(outside)
        return True

    confirmer.confirm = AsyncMock(side_effect=approve_then_replace)
    result = await ScriptRunner(sandbox, confirmer, [tmp_path]).run_script(
        doc, "run.py", ()
    )

    assert result.success is False
    sandbox.run.assert_not_called()
    assert "symlink" in result.error.lower() or "符号链接" in result.error


@pytest.mark.asyncio()
async def test_sandbox_enforces_bounded_output(tmp_path):
    script = tmp_path / "spam.py"
    script.write_text("print('x' * 10000)", encoding="utf-8")
    result = await SubprocessSandboxAdapter(max_output_bytes=128).run(
        SandboxRequest(script_path=script)
    )

    assert result.success is False
    assert "output" in (result.error or "").lower()
    assert len(result.stdout.encode("utf-8")) <= 128
    assert result.exit_code != 0


@pytest.mark.asyncio()
async def test_sandbox_starts_posix_process_group(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("print('ok')", encoding="utf-8")
    adapter = SubprocessSandboxAdapter()
    request = SandboxRequest(script_path=script)
    fake = AsyncMock()
    fake.communicate = AsyncMock(return_value=(b"ok\n", b""))
    fake.wait = AsyncMock()
    fake.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=fake) as spawn:
        await adapter.run(request)
    if os.name == "posix":
        assert spawn.call_args.kwargs["start_new_session"] is True
