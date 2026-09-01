"""M7 测试: ScriptRunner 编排。

覆盖 backend.skills.skill_md.script_runner:
- ScriptRunner 基本构造
- run_script 完整流程 (happy path)
- 路径校验失败
- 脚本不存在
- 用户拒绝执行
- 沙箱执行失败
- 沙箱超时
- 异常收敛
- metadata 完整性
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.skills.skill_md.confirm import ConfirmationPort
from backend.skills.skill_md.sandbox import SandboxPort, SandboxRequest, SandboxResult
from backend.skills.skill_md.script_runner import ScriptRunner
from backend.skills.skill_md.skill import SkillMdDocument

pytestmark = pytest.mark.unit


def _make_doc(name: str = "test-skill", base_dir: Optional[Path] = None) -> SkillMdDocument:
    """创建测试用的 SkillMdDocument。"""
    return SkillMdDocument(
        name=name,
        description="Test skill",
        base_dir=base_dir or Path("/tmp/skills/test-skill"),
    )


# =====================================================================
# ScriptRunner 基本构造
# =====================================================================


def test_script_runner_basic_construction():
    """ScriptRunner 基本构造。"""
    sandbox = MagicMock(spec=SandboxPort)
    confirmer = MagicMock(spec=ConfirmationPort)
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer)
    assert runner._sandbox is sandbox
    assert runner._confirmer is confirmer
    assert runner._allowed_roots == []


def test_script_runner_with_allowed_roots():
    """ScriptRunner 接受 allowed_roots 列表。"""
    sandbox = MagicMock(spec=SandboxPort)
    confirmer = MagicMock(spec=ConfirmationPort)
    allowed_roots = [Path("/tmp/skills"), Path("/home/user/.sage/skills")]
    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=allowed_roots,
    )
    assert runner._allowed_roots == allowed_roots


# =====================================================================
# ScriptRunner.run_script - Happy Path
# =====================================================================


@pytest.mark.asyncio()
async def test_script_runner_happy_path(tmp_path):
    """完整 happy path: 校验 → 确认 → 沙箱 → SkillResult 成功。"""
    # 设置技能目录
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "test_script.py"
    script.write_text("print('hello')\n", encoding="utf-8")

    doc = _make_doc(name="my-skill", base_dir=tmp_path)

    # Mock SandboxPort
    sandbox_result = SandboxResult(
        success=True,
        exit_code=0,
        stdout="hello\n",
        stderr="",
        duration_ms=100,
    )
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock(return_value=sandbox_result)

    # Mock ConfirmationPort (auto-approve)
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    result = await runner.run_script(
        doc=doc,
        script_name="scripts/test_script.py",
        args=(),
    )

    # 验证结果
    assert result.success is True
    assert result.content == "hello\n"
    assert result.metadata["source"] == "script_execution"
    assert result.metadata["script"] == "scripts/test_script.py"
    assert result.metadata["exit_code"] == 0
    assert result.error is None

    # 验证 confirmer 和 sandbox 被调用
    confirmer.confirm.assert_called_once()
    sandbox.run.assert_called_once()

    # 验证 SandboxRequest 参数
    call_args = sandbox.run.call_args
    req = call_args.args[0]
    assert isinstance(req, SandboxRequest)
    assert req.script_path != script.resolve()
    assert req.script_path.name == script.name
    assert req.cwd == script.parent.resolve()


@pytest.mark.asyncio()
async def test_script_runner_with_args(tmp_path):
    """ScriptRunner 传递 args 给沙箱。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "test.py"
    script.write_text("print('args')\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock(
        return_value=SandboxResult(
            success=True,
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=10,
        ),
    )
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    await runner.run_script(doc=doc, script_name="scripts/test.py", args=("arg1", "arg2"))

    req = sandbox.run.call_args.args[0]
    assert req.args == ("arg1", "arg2")


# =====================================================================
# ScriptRunner.run_script - 路径校验
# =====================================================================


@pytest.mark.asyncio()
async def test_script_runner_rejects_traversal(tmp_path):
    """ScriptRunner 拒绝路径遍历（../ 跳出 allowed_roots）。"""
    base = tmp_path / "skills"
    base.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret\n", encoding="utf-8")

    doc = _make_doc(base_dir=base)

    # 恶意脚本名（试图通过 ../ 跳出）
    evil_script_name = "../secret.txt"

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[base],
    )

    result = await runner.run_script(doc=doc, script_name=evil_script_name, args=())

    # 应该返回失败，不执行沙箱，不调用 confirmer（路径校验先于确认）
    assert result.success is False
    assert "not under any allowed root" in result.error
    sandbox.run.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_rejects_script_not_in_base_dir(tmp_path):
    """ScriptRunner 拒绝不在 base_dir 内的脚本。"""
    base = tmp_path / "skills"
    base.mkdir()
    scripts_dir = base / "scripts"
    scripts_dir.mkdir()

    # 在 base_dir 之外创建脚本
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_script = outside / "evil.py"
    outside_script.write_text("print('evil')\n", encoding="utf-8")

    doc = _make_doc(base_dir=base)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[base],
    )

    # 引用 outside_script（通过 ..）
    result = await runner.run_script(
        doc=doc,
        script_name=f"../{outside_script.name}",
        args=(),
    )

    assert result.success is False
    sandbox.run.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_rejects_absolute_script_path(tmp_path):
    """绝对路径不能跳过当前技能目录边界。"""
    base = tmp_path / "skill-a"
    base.mkdir()
    outside = tmp_path / "skill-b.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    doc = _make_doc(base_dir=base)
    sandbox = MagicMock(spec=SandboxPort)
    confirmer = MagicMock(spec=ConfirmationPort)
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])

    result = await runner.run_script(doc=doc, script_name=str(outside), args=())

    assert result.success is False
    assert "skill" in result.error.lower() or "路径" in result.error
    confirmer.confirm.assert_not_called()
    sandbox.run.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_rejects_symlink_component(tmp_path):
    """技能目录内的符号链接不能把脚本解析到另一技能。"""
    base = tmp_path / "skill-a"
    other = tmp_path / "skill-b"
    base.mkdir()
    other.mkdir()
    target = other / "evil.py"
    target.write_text("print('outside')\n", encoding="utf-8")
    link = base / "scripts"
    link.symlink_to(other, target_is_directory=True)
    doc = _make_doc(base_dir=base)
    sandbox = MagicMock(spec=SandboxPort)
    confirmer = MagicMock(spec=ConfirmationPort)
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])

    result = await runner.run_script(doc=doc, script_name="scripts/evil.py", args=())

    assert result.success is False
    confirmer.confirm.assert_not_called()
    sandbox.run.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_accepts_script_in_nested_subdir(tmp_path):
    """ScriptRunner 接受嵌套子目录中的脚本。"""
    base = tmp_path / "skills"
    base.mkdir()
    nested = base / "scripts" / "subdir"
    nested.mkdir(parents=True)
    script = nested / "deep.py"
    script.write_text("print('deep')\n", encoding="utf-8")

    doc = _make_doc(base_dir=base)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock(
        return_value=SandboxResult(
            success=True,
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=10,
        ),
    )
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[base],
    )

    result = await runner.run_script(doc=doc, script_name="scripts/subdir/deep.py", args=())

    assert result.success is True
    sandbox.run.assert_called_once()


# =====================================================================
# ScriptRunner.run_script - 用户确认
# =====================================================================


@pytest.mark.asyncio()
async def test_script_runner_user_declined_returns_error(tmp_path):
    """用户拒绝 → success=False，不执行沙箱。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "test.py"
    script.write_text("print('test')\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=False)  # 用户拒绝

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    result = await runner.run_script(doc=doc, script_name="scripts/test.py", args=())

    assert result.success is False
    assert (
        "declined" in result.error.lower()
        or "拒绝" in result.error
        or "user" in result.error.lower()
    )
    sandbox.run.assert_not_called()


# =====================================================================
# ScriptRunner.run_script - 确认后快照
# =====================================================================


@pytest.mark.asyncio()
async def test_script_runner_rejects_content_changed_after_confirmation(tmp_path):
    """确认后普通文件内容变化必须 fail-closed。"""
    script = tmp_path / "test.py"
    script.write_text("print('before')\n", encoding="utf-8")
    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()

    async def confirm_then_change(**kwargs):
        script.write_text("print('after')\n", encoding="utf-8")
        return True

    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = confirm_then_change
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])

    result = await runner.run_script(doc, "test.py", ())

    assert result.success is False
    assert "变化" in result.error or "changed" in result.error.lower() or "hash" in result.error.lower()
    sandbox.run.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_rejects_replaced_regular_file_after_confirmation(tmp_path):
    """确认后替换为另一普通文件即使内容不同也必须拒绝。"""
    script = tmp_path / "test.py"
    script.write_text("print('before')\n", encoding="utf-8")
    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()

    async def confirm_then_replace(**kwargs):
        replacement = tmp_path / "replacement.py"
        replacement.write_text("print('after')\n", encoding="utf-8")
        os.replace(str(replacement), str(script))
        return True

    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = confirm_then_replace
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])

    result = await runner.run_script(doc, "test.py", ())

    assert result.success is False
    assert "changed" in result.error.lower() or "变化" in result.error
    sandbox.run.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_rejects_same_hash_different_inode_after_confirmation(tmp_path):
    """确认后 inode 改变但 SHA-256 不变仍必须拒绝（不能只依赖 hash）。"""
    script = tmp_path / "test.py"
    content = b"print('same')\n"
    script.write_bytes(content)
    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()

    async def confirm_then_replace_same_content(**kwargs):
        replacement = tmp_path / "replacement.py"
        replacement.write_bytes(content)
        os.replace(str(replacement), str(script))
        return True

    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = confirm_then_replace_same_content
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])

    result = await runner.run_script(doc, "test.py", ())

    assert result.success is False
    assert "identity" in result.error.lower() or "inode" in result.error.lower()
    sandbox.run.assert_not_called()
@pytest.mark.asyncio()
async def test_script_runner_executes_private_snapshot_and_cleans_it(tmp_path):
    """沙箱接收受控快照，权限正确且执行后清理。"""
    script = tmp_path / "test.py"
    content = "print('snapshot')\n"
    script.write_text(content, encoding="utf-8")
    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        captured["request"] = request
        assert request.script_path.read_text(encoding="utf-8") == content
        assert stat.S_IMODE(request.script_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(request.script_path.parent.stat().st_mode) == 0o700
        return SandboxResult(True, 0, "ok", "", 1)

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])

    result = await runner.run_script(doc, "test.py", ())

    assert result.success is True
    snapshot = captured["request"].script_path
    assert snapshot != script.resolve()
    assert not snapshot.exists()
    assert not snapshot.parent.exists()


    """沙箱异常时也必须清理快照。"""
    script = tmp_path / "test.py"
    script.write_text("print('x')\n", encoding="utf-8")
    doc = _make_doc(base_dir=tmp_path)
    captured = {}

    async def run(request):
        captured["path"] = request.script_path
        raise RuntimeError("boom")

    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = run
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])

    result = await runner.run_script(doc, "test.py", ())

    assert result.success is False
    assert not captured["path"].parent.exists()


@pytest.mark.asyncio()
async def test_script_runner_rejects_snapshot_creation_failure(tmp_path, monkeypatch):
    """快照无法安全创建时必须拒绝执行。"""
    script = tmp_path / "test.py"
    script.write_text("print('x')\n", encoding="utf-8")
    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])
    monkeypatch.setattr(runner, "_create_snapshot", lambda path, content: (_ for _ in ()).throw(OSError("no snapshot")))

    result = await runner.run_script(doc, "test.py", ())

    assert result.success is False
    assert "快照" in result.error
    sandbox.run.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_fails_closed_without_o_nofollow(tmp_path, monkeypatch):
    """不支持 O_NOFOLLOW 时拒绝读取，且不进入确认或沙箱。"""
    script = tmp_path / "test.py"
    script.write_text("print('x')\n", encoding="utf-8")
    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[tmp_path])
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)

    result = await runner.run_script(doc, "test.py", ())

    assert result.success is False
    confirmer.confirm.assert_not_called()
    sandbox.run.assert_not_called()




@pytest.mark.asyncio()
async def test_script_runner_sandbox_failure_returns_error(tmp_path):
    """沙箱失败（exit_code != 0）→ success=False。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "fail.py"
    script.write_text("raise Exception\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock(
        return_value=SandboxResult(
            success=False,
            exit_code=1,
            stdout="",
            stderr="Error",
            duration_ms=10,
        ),
    )
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    result = await runner.run_script(doc=doc, script_name="scripts/fail.py", args=())

    assert result.success is False
    assert result.metadata["exit_code"] == 1


@pytest.mark.asyncio()
async def test_script_runner_sandbox_timeout_returns_error(tmp_path):
    """沙箱超时 → success=False, timed_out=True。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "slow.py"
    script.write_text("time.sleep(10)\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock(
        return_value=SandboxResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            duration_ms=30000,
            timed_out=True,
            error="timeout after 30.0s",
        ),
    )
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    result = await runner.run_script(doc=doc, script_name="scripts/slow.py", args=())

    assert result.success is False
    assert "timeout" in result.error.lower()


# =====================================================================
# ScriptRunner.run_script - 异常处理
# =====================================================================


@pytest.mark.asyncio()
async def test_script_runner_sandbox_exception_does_not_propagate(tmp_path):
    """沙箱抛异常 → 收敛为 success=False，不向上传播。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "test.py"
    script.write_text("print('test')\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock(side_effect=Exception("sandbox crashed"))
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    # 不应抛异常
    result = await runner.run_script(doc=doc, script_name="scripts/test.py", args=())

    assert result.success is False
    assert "sandbox crashed" in result.error or "exception" in result.error.lower()


@pytest.mark.asyncio()
async def test_script_runner_confirmer_exception_does_not_propagate(tmp_path):
    """confirmer 抛异常 → 收敛为 success=False（默认拒绝）。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "test.py"
    script.write_text("print('test')\n", encoding="utf-8")

    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(side_effect=Exception("confirmer crashed"))

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    # 不应抛异常
    result = await runner.run_script(doc=doc, script_name="scripts/test.py", args=())

    assert result.success is False
    sandbox.run.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_invalid_path_construction_is_converged():
    """doc.base_dir/script_name 构造异常时也应返回失败结果。"""
    doc = _make_doc(base_dir=object())  # type: ignore[arg-type]
    sandbox = MagicMock(spec=SandboxPort)
    confirmer = MagicMock(spec=ConfirmationPort)
    runner = ScriptRunner(sandbox=sandbox, confirmer=confirmer, allowed_roots=[])

    result = await runner.run_script(doc=doc, script_name="script.py", args=())

    assert result.success is False
    assert result.error is not None
    sandbox.run.assert_not_called()
    confirmer.confirm.assert_not_called()


@pytest.mark.asyncio()
async def test_script_runner_invalid_args_are_converged(tmp_path):
    """args 非 tuple[str, ...] 时应返回失败结果而不是抛异常。"""
    script = tmp_path / "test.py"
    script.write_text("print('test')\n", encoding="utf-8")
    doc = _make_doc(base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    confirmer = MagicMock(spec=ConfirmationPort)
    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    result = await runner.run_script(
        doc=doc,
        script_name="test.py",
        args=("valid", 123),  # type: ignore[arg-type]
    )

    assert result.success is False
    assert result.error is not None
    sandbox.run.assert_not_called()
    confirmer.confirm.assert_not_called()


# =====================================================================
# ScriptRunner.run_script - 路径校验先于确认
# =====================================================================


@pytest.mark.asyncio()
async def test_script_runner_path_validation_before_confirmation(tmp_path):
    """路径校验失败时，不应调用 confirmer (短路优化)。"""
    base = tmp_path / "skills"
    base.mkdir()
    doc = _make_doc(base_dir=base)

    sandbox = MagicMock(spec=SandboxPort)
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[base],
    )

    # 非法脚本名
    result = await runner.run_script(doc=doc, script_name="../../etc/passwd", args=())

    assert result.success is False
    confirmer.confirm.assert_not_called()


# =====================================================================
# ScriptRunner.run_script - metadata 完整性
# =====================================================================


@pytest.mark.asyncio()
async def test_script_runner_metadata_includes_execution_info(tmp_path):
    """SkillResult.metadata 包含完整执行信息。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "test.py"
    script.write_text("print('test')\n", encoding="utf-8")

    doc = _make_doc(name="my-skill", base_dir=tmp_path)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock(
        return_value=SandboxResult(
            success=True,
            exit_code=0,
            stdout="output\n",
            stderr="warning\n",
            duration_ms=150,
        ),
    )
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[tmp_path],
    )

    result = await runner.run_script(
        doc=doc,
        script_name="scripts/test.py",
        args=("arg1",),
    )

    assert result.metadata["source"] == "script_execution"
    assert result.metadata["script"] == "scripts/test.py"
    assert result.metadata["exit_code"] == 0
    assert result.metadata["duration_ms"] == 150
    assert result.metadata["stderr"] == "warning\n"


# =====================================================================
# ScriptRunner.run_script - 不存在的脚本
# =====================================================================


@pytest.mark.asyncio()
async def test_script_runner_nonexistent_script(tmp_path):
    """脚本不存在 → success=False，不执行沙箱。"""
    base = tmp_path / "skills"
    base.mkdir()
    scripts_dir = base / "scripts"
    scripts_dir.mkdir()

    doc = _make_doc(base_dir=base)
    sandbox = MagicMock(spec=SandboxPort)
    sandbox.run = AsyncMock()
    confirmer = MagicMock(spec=ConfirmationPort)
    confirmer.confirm = AsyncMock(return_value=True)

    runner = ScriptRunner(
        sandbox=sandbox,
        confirmer=confirmer,
        allowed_roots=[base],
    )

    # 引用不存在的脚本（路径在 base_dir 内但文件不存在）
    result = await runner.run_script(doc=doc, script_name="scripts/nonexistent.py", args=())

    assert result.success is False
    assert "not found" in result.error.lower() or "不存在" in result.error
    sandbox.run.assert_not_called()
