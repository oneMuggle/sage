"""T-2 脚本调度可达专项测试。

验证 slash / skill-tool 路径能把脚本执行请求送到 SKILL.md 的 script_runner,
且**必须经过权限闸口**（``InprocSkillAdapter._enforce_permission``）——
与 REST ``POST /skills/{name}/execute`` 同一权限模型。

覆盖:
- ``_extract_script_from_args`` 前缀解析（含空值拒绝）
- ``execute_command`` 带 ``script=`` 前缀 → 路由到 script_runner
- 权限闸口：deny 时拒绝执行并打 ``permission_denied`` 标记
- 权限闸口：allow 时放行
- 无 ``script=`` 前缀时行为不变（返回 body，且不触发权限检查）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from backend.adapters.out.skill.inproc import InprocSkillAdapter
from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.skill import DispatchMode, SkillMdDocument, SkillMdSkill
from backend.tools.permissions import PermissionDecision

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 存根
# ---------------------------------------------------------------------------


class _StubScriptRunner:
    """记录 ``run_script`` 调用并返回成功结果。"""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Tuple[str, ...]]] = []

    async def run_script(self, doc: Any, script_name: str, args: Tuple[str, ...]) -> Any:
        self.calls.append((script_name, tuple(args)))
        from backend.skills.base import SkillResult as BaseSkillResult

        return BaseSkillResult(
            success=True,
            content=f"ran:{script_name}:{list(args)}",
            metadata={"source": "script_execution"},
        )


class _StubEnforcer:
    """记录 ``check`` 调用次数，返回预置决策。"""

    def __init__(self, decision: PermissionDecision) -> None:
        self._decision = decision
        self.calls: List[Tuple[str, Optional[Dict[str, Any]]]] = []

    def check(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> PermissionDecision:
        self.calls.append((tool_name, args))
        return self._decision


def _allow() -> PermissionDecision:
    return PermissionDecision(allowed=True, needs_approval=False, reason="allow")


def _deny() -> PermissionDecision:
    return PermissionDecision(allowed=False, needs_approval=False, reason="未授权脚本")


def _build_adapter(
    tmp_path: Path,
    enforcer: _StubEnforcer,
    script_runner: _StubScriptRunner,
    skill_name: str = "t2-script-skill",
) -> InprocSkillAdapter:
    """装配含单个 user_invocable SKILL.md 技能的 adapter。"""
    doc = SkillMdDocument(
        name=skill_name,
        description="T-2 脚本调度测试技能",
        body="skill body",
        base_dir=tmp_path,
        dispatch=DispatchMode(user_invocable=True),
    )
    skill = SkillMdSkill(doc=doc, base_dir=tmp_path, script_runner=script_runner)
    registry = SkillRegistry()
    registry.register(skill)
    return InprocSkillAdapter(
        registry=registry,
        enforcer_factory=lambda: enforcer,
    )


# ---------------------------------------------------------------------------
# _extract_script_from_args
# ---------------------------------------------------------------------------


def test_extract_script_from_args_parses_script_prefix():
    """args 首个元素 ``script=<path>`` → 提取路径，剩余元素作为脚本参数。"""
    # Act
    script, rest = InprocSkillAdapter._extract_script_from_args(
        ["script=scripts/scan.py", "--fast", "src/"]
    )

    # Assert
    assert script == "scripts/scan.py"
    assert rest == ["--fast", "src/"]


def test_extract_script_from_args_without_prefix_returns_none():
    """无 script 前缀时返回 (None, 原参数)。"""
    # Act
    script, rest = InprocSkillAdapter._extract_script_from_args(["--fast", "src/"])

    # Assert
    assert script is None
    assert rest == ["--fast", "src/"]


def test_extract_script_from_args_empty_list():
    """空参数列表 → (None, [])。"""
    # Act
    script, rest = InprocSkillAdapter._extract_script_from_args([])

    # Assert
    assert script is None
    assert rest == []


def test_extract_script_from_args_rejects_empty_script_value():
    """``script=``（空路径）不被当作脚本分发 → 保留原参数。"""
    # Act
    script, rest = InprocSkillAdapter._extract_script_from_args(["script=", "arg"])

    # Assert
    assert script is None
    assert rest == ["script=", "arg"]


def test_extract_script_from_args_only_matches_first_element():
    """只有首个元素参与前缀解析，后续元素即使形如 script= 也不解析。"""
    # Act
    script, rest = InprocSkillAdapter._extract_script_from_args(
        ["arg", "script=scripts/other.py"]
    )

    # Assert
    assert script is None
    assert rest == ["arg", "script=scripts/other.py"]


# ---------------------------------------------------------------------------
# execute_command：script= 前缀 → 权限闸口 → script_runner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_execute_command_script_prefix_runs_script(tmp_path):
    """slash ``script=`` 前缀 → script_runner 收到脚本名与剩余参数。"""
    # Arrange
    enforcer = _StubEnforcer(_allow())
    runner = _StubScriptRunner()
    adapter = _build_adapter(tmp_path, enforcer, runner)

    # Act
    result = await adapter.execute_command(
        "/t2-script-skill", ["script=scripts/scan.py", "--fast"]
    )

    # Assert
    assert result.success is True
    assert runner.calls == [("scripts/scan.py", ("--fast",))]


@pytest.mark.asyncio()
async def test_execute_command_script_prefix_consults_permission_gate(tmp_path):
    """关键回归：slash 路径的脚本分发**必须**经过权限闸口。"""
    # Arrange
    enforcer = _StubEnforcer(_allow())
    runner = _StubScriptRunner()
    adapter = _build_adapter(tmp_path, enforcer, runner)

    # Act
    await adapter.execute_command("/t2-script-skill", ["script=scripts/scan.py"])

    # Assert — enforcer.check("skill", ...) 被调用过一次
    assert len(enforcer.calls) == 1
    tool_name, checked_args = enforcer.calls[0]
    assert tool_name == "skill"
    assert checked_args is not None
    assert checked_args.get("script") == "scripts/scan.py"


@pytest.mark.asyncio()
async def test_execute_command_script_prefix_denied_without_allowlist(tmp_path):
    """权限拒绝时脚本不执行，返回 permission_denied 标记。"""
    # Arrange
    enforcer = _StubEnforcer(_deny())
    runner = _StubScriptRunner()
    adapter = _build_adapter(tmp_path, enforcer, runner)

    # Act
    result = await adapter.execute_command("/t2-script-skill", ["script=scripts/scan.py"])

    # Assert
    assert result.success is False
    assert result.metadata.get("permission_denied") is True
    assert "权限拒绝" in (result.error or "")
    # 脚本未被执行
    assert runner.calls == []


@pytest.mark.asyncio()
async def test_execute_command_script_prefix_needs_approval_is_denied(tmp_path):
    """``needs_approval=True`` 时同样拒绝（REST 路径无审批通道，fail closed）。"""
    # Arrange
    enforcer = _StubEnforcer(
        PermissionDecision(allowed=False, needs_approval=True, reason="需审批")
    )
    runner = _StubScriptRunner()
    adapter = _build_adapter(tmp_path, enforcer, runner)

    # Act
    result = await adapter.execute_command("/t2-script-skill", ["script=scripts/scan.py"])

    # Assert
    assert result.success is False
    assert result.metadata.get("permission_denied") is True
    assert runner.calls == []


@pytest.mark.asyncio()
async def test_execute_command_without_script_prefix_returns_body(tmp_path):
    """无 script 前缀 → 走 slash_registry 返回 body，且不触发权限检查。"""
    # Arrange
    enforcer = _StubEnforcer(_deny())
    runner = _StubScriptRunner()
    adapter = _build_adapter(tmp_path, enforcer, runner)

    # Act
    result = await adapter.execute_command("/t2-script-skill", ["--fast"])

    # Assert
    assert result.success is True
    assert result.content == "skill body"
    assert enforcer.calls == []
    assert runner.calls == []
