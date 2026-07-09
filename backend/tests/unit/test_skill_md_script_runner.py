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
    assert req.script_path == script.resolve()
    assert req.args == ()


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
# ScriptRunner.run_script - 沙箱执行
# =====================================================================


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
