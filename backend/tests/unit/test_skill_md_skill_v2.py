# mypy: disable-error-code="no-untyped-def,attr-defined,func-returns-value"
"""M8 测试: SkillMdSkill.execute_v2 路径。

覆盖 backend.skills.skill_md.skill.SkillMdSkill:
- execute_v2 没有 ScriptRunner → 回退到 v1 (返回 body)
- execute_v2 没有 'script' 参数 → 回退到 v1
- execute_v2 有 'script' 参数 → 委托 ScriptRunner.run_script
- args 列表 → 转换为 tuple 传给 runner
- runner 返回的 SkillResult 透传
- execute() v1 行为不变 (向后兼容)
- execute_v2() 是 async (与 ScriptRunner.run_script 对齐)
"""

from __future__ import annotations
from typing import List, Optional

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.skills.base import SkillResult
from backend.skills.skill_md.script_runner import ScriptRunner
from backend.skills.skill_md.skill import SkillMdDocument, SkillMdSkill

pytestmark = pytest.mark.unit


def _make_doc(
    name: str = "test-skill",
    description: str = "A test skill",
    triggers: Optional[List[str]] = None,
    body: str = "Body content",
    base_dir: Optional[Path] = None,
) -> SkillMdDocument:
    return SkillMdDocument(
        name=name,
        description=description,
        triggers=triggers or [],
        body=body,
        base_dir=base_dir or Path("/tmp/skills/test-skill"),
    )


def _make_runner_mock() -> MagicMock:
    """构造 ScriptRunner mock（spec=ScriptRunner 强制接口对齐）。"""
    return MagicMock(spec=ScriptRunner)


# =====================================================================
# execute_v2 - 回退路径（无 ScriptRunner / 无 script 字段）
# =====================================================================


@pytest.mark.asyncio()
async def test_execute_v2_without_script_runner_falls_back_to_v1(tmp_path):
    """execute_v2 未注入 ScriptRunner → 回退到 v1，返回 body。

    关键不变量：现有不传 ScriptRunner 的代码路径必须保持完全兼容。
    """
    doc = _make_doc(body="static v1 body")
    skill = SkillMdSkill(doc, base_dir=tmp_path)

    result = await skill.execute_v2(params={}, context={})

    assert result.success is True
    assert result.content == "static v1 body"
    assert result.metadata["source"] == "skillmd"


@pytest.mark.asyncio()
async def test_execute_v2_without_script_name_falls_back_to_v1(tmp_path):
    """execute_v2 params 中无 'script' 字段 → 回退到 v1，不调用 runner。"""
    doc = _make_doc(body="static v1 body")
    runner = _make_runner_mock()
    runner.run_script = AsyncMock()
    skill = SkillMdSkill(doc, base_dir=tmp_path, script_runner=runner)

    result = await skill.execute_v2(
        params={"some_other_param": "value"},
        context={},
    )

    assert result.success is True
    assert result.content == "static v1 body"
    runner.run_script.assert_not_called()


# =====================================================================
# execute_v2 - 委托 ScriptRunner 路径
# =====================================================================


@pytest.mark.asyncio()
async def test_execute_v2_with_script_name_dispatches_to_runner(tmp_path):
    """execute_v2 params 含 'script' → 委托 ScriptRunner.run_script。"""
    doc = _make_doc(base_dir=tmp_path)
    runner_result = SkillResult(
        success=True,
        content="runner output",
        metadata={"source": "script_execution"},
    )
    runner = _make_runner_mock()
    runner.run_script = AsyncMock(return_value=runner_result)
    skill = SkillMdSkill(doc, base_dir=tmp_path, script_runner=runner)

    result = await skill.execute_v2(
        params={"script": "scripts/foo.py"},
        context={},
    )

    assert result is runner_result
    runner.run_script.assert_called_once()
    call_kwargs = runner.run_script.call_args.kwargs
    assert call_kwargs["doc"] is doc
    assert call_kwargs["script_name"] == "scripts/foo.py"
    assert call_kwargs["args"] == ()


@pytest.mark.asyncio()
async def test_execute_v2_passes_args_as_tuple(tmp_path):
    """execute_v2 params['args'] (list) → tuple 传给 runner。"""
    doc = _make_doc(base_dir=tmp_path)
    runner = _make_runner_mock()
    runner.run_script = AsyncMock(
        return_value=SkillResult(success=True, content="out", metadata={}),
    )
    skill = SkillMdSkill(doc, base_dir=tmp_path, script_runner=runner)

    await skill.execute_v2(
        params={"script": "scripts/foo.py", "args": ["a", "b", "c"]},
        context={},
    )

    call_kwargs = runner.run_script.call_args.kwargs
    assert call_kwargs["args"] == ("a", "b", "c")
    assert isinstance(call_kwargs["args"], tuple)


@pytest.mark.asyncio()
async def test_execute_v2_without_args_uses_empty_tuple(tmp_path):
    """execute_v2 params 中无 'args' 键 → 空 tuple 传给 runner。"""
    doc = _make_doc(base_dir=tmp_path)
    runner = _make_runner_mock()
    runner.run_script = AsyncMock(
        return_value=SkillResult(success=True, content="out", metadata={}),
    )
    skill = SkillMdSkill(doc, base_dir=tmp_path, script_runner=runner)

    await skill.execute_v2(
        params={"script": "scripts/foo.py"},
        context={},
    )

    call_kwargs = runner.run_script.call_args.kwargs
    assert call_kwargs["args"] == ()


@pytest.mark.asyncio()
async def test_execute_v2_propagates_runner_failure(tmp_path):
    """runner 返回 success=False → execute_v2 透传失败结果。"""
    doc = _make_doc(base_dir=tmp_path)
    failure = SkillResult(
        success=False,
        content=None,
        metadata={"exit_code": 1},
        error="script failed",
    )
    runner = _make_runner_mock()
    runner.run_script = AsyncMock(return_value=failure)
    skill = SkillMdSkill(doc, base_dir=tmp_path, script_runner=runner)

    result = await skill.execute_v2(
        params={"script": "scripts/fail.py"},
        context={},
    )

    assert result.success is False
    assert result.error == "script failed"
    assert result.metadata["exit_code"] == 1


# =====================================================================
# 向后兼容：execute() v1 行为必须不变
# =====================================================================


def test_execute_v1_unchanged_after_v2_added(tmp_path):
    """添加 execute_v2 后，execute() v1 行为完全不变（CRITICAL 兼容性约束）。"""
    doc = _make_doc(
        name="legacy",
        body="legacy body",
        triggers=["legacy"],
    )
    skill = SkillMdSkill(doc, base_dir=tmp_path)

    result = skill.execute(params={}, context={})

    assert result.success is True
    assert result.content == "legacy body"
    assert result.metadata["source"] == "skillmd"
    assert result.metadata["name"] == "legacy"


def test_skill_md_skill_constructor_accepts_script_runner_kwarg(tmp_path):
    """SkillMdSkill 构造器接受 script_runner kwarg（默认 None）。"""
    doc = _make_doc(base_dir=tmp_path)

    # 默认 None
    skill_default = SkillMdSkill(doc, base_dir=tmp_path)
    assert skill_default._script_runner is None

    # 显式传
    runner = _make_runner_mock()
    skill_with_runner = SkillMdSkill(
        doc,
        base_dir=tmp_path,
        script_runner=runner,
    )
    assert skill_with_runner._script_runner is runner
