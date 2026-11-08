"""Phase 3 hook 反馈注入单元测试。

覆盖:
- HookOutcome.additional_context / severity 解析
- run_event_hooks 多钩子反馈聚合 (拼接 + severity 取最严格)
- _merge_feedback 截断
- 反馈文本在 LLM context 中不被泄漏为空内容
"""

from __future__ import annotations

import json
import sys

import pytest

from backend.hooks.config import HookConfig
from backend.hooks.runner import (
    HookOutcome,
    _merge_feedback,
    build_payload,
    run_event_hooks,
    run_hook,
)

pytestmark = [
    pytest.mark.unit,
    # Windows cmd.exe 不解释 shell 命令中的单引号 → -c 参数解析失败 (产品级 Windows 兼容缺口)
    pytest.mark.skipif(sys.platform == "win32", reason="hooks shell 引用在 Windows cmd.exe 下不兼容（产品缺口）"),
]

PY = sys.executable


def _cfg(command: str, event: str = "post_tool_use", matcher: str = "*", timeout: float = 5.0) -> HookConfig:
    return HookConfig(event=event, command=command, matcher=matcher, timeout_seconds=timeout)


def _post_payload(tool_name: str = "bash", content: str = "ok") -> dict:
    return build_payload("post_tool_use", tool_name, {"command": "echo hi"}, tool_output=content)


# ==================== HookOutcome 字段 ====================


def test_hookoutcome_has_feedback_flag():
    assert HookOutcome(additional_context="lint: 3 issues").has_feedback
    assert not HookOutcome().has_feedback
    assert not HookOutcome(additional_context="").has_feedback
    assert not HookOutcome(additional_context=None).has_feedback


def test_hookoutcome_default_severity_is_info():
    assert HookOutcome().severity == "info"


# ==================== _parse_decision_dict 路径 ====================


@pytest.mark.asyncio()
async def test_hook_stdout_additional_context_captured():
    cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "ruff: F401 unused import on line 5", """
        f""""severity": "warning"}}))'"""
    )
    outcome = await run_hook(_cfg(cmd), _post_payload())
    assert outcome.additional_context == "ruff: F401 unused import on line 5"
    assert outcome.severity == "warning"


@pytest.mark.asyncio()
async def test_hook_stdout_truncates_oversized_feedback():
    huge = "x" * 5000
    cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": {json.dumps(huge)}}}))'"""
    )
    outcome = await run_hook(_cfg(cmd), _post_payload())
    assert outcome.additional_context is not None
    assert len(outcome.additional_context) <= 2048 + 10  # 截断后缀


@pytest.mark.asyncio()
async def test_hook_invalid_severity_falls_back_to_info():
    cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "msg", "severity": "criticallll"}}))'"""
    )
    outcome = await run_hook(_cfg(cmd), _post_payload())
    assert outcome.severity == "info"


@pytest.mark.asyncio()
async def test_hook_feedback_on_deny_still_propagates():
    cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny", """
        f""""reason": "blocked", "additional_context": "see docs"}}))'"""
    )
    outcome = await run_hook(_cfg(cmd), _post_payload())
    assert outcome.denied
    assert outcome.additional_context == "see docs"


# ==================== 多钩子聚合 ====================


@pytest.mark.asyncio()
async def test_run_event_hooks_merges_multiple_feedbacks():
    cmd1 = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "line 1: unused import"}}))'"""
    )
    cmd2 = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "line 5: typo"}}))'"""
    )
    hooks = [_cfg(cmd1), _cfg(cmd2)]
    outcome = await run_event_hooks(hooks, "post_tool_use", "bash", _post_payload())
    assert outcome.has_feedback
    assert "line 1: unused import" in outcome.additional_context
    assert "line 5: typo" in outcome.additional_context


@pytest.mark.asyncio()
async def test_run_event_hooks_severity_takes_highest():
    info_cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "info msg", "severity": "info"}}))'"""
    )
    err_cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "err msg", "severity": "error"}}))'"""
    )
    warn_cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "warn msg", "severity": "warning"}}))'"""
    )
    outcome = await run_event_hooks(
        [_cfg(info_cmd), _cfg(warn_cmd), _cfg(err_cmd)],
        "post_tool_use",
        "bash",
        _post_payload(),
    )
    assert outcome.severity == "error"


@pytest.mark.asyncio()
async def test_run_event_hooks_feedback_on_deny_still_aggregated():
    """deny 短路时仍把之前已收集的反馈带上。"""
    info_cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "first observation"}}))'"""
    )
    deny_cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny", "reason": "no"}}))'"""
    )
    outcome = await run_event_hooks(
        [_cfg(info_cmd), _cfg(deny_cmd)], "post_tool_use", "bash", _post_payload()
    )
    assert outcome.denied
    assert outcome.additional_context == "first observation"


@pytest.mark.asyncio()
async def test_run_event_hooks_no_feedback_when_none_provided():
    cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow"}}))'"""
    outcome = await run_event_hooks([_cfg(cmd)], "post_tool_use", "bash", _post_payload())
    assert not outcome.has_feedback
    assert outcome.additional_context is None


# ==================== _merge_feedback ====================


def test_merge_feedback_joins_with_newlines():
    assert _merge_feedback(["a", "b", "c"]) == "a\nb\nc"


def test_merge_feedback_caps_length():
    parts = ["a" * 3000, "b" * 3000]
    result = _merge_feedback(parts)
    assert len(result) <= 4096 + 10


def test_merge_feedback_empty():
    assert _merge_feedback([]) == ""


def test_merge_feedback_single():
    assert _merge_feedback(["solo"]) == "solo"
