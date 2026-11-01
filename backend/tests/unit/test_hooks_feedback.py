"""Phase 3 hook 反馈注入单元测试。

覆盖:
- HookOutcome.additional_context / severity 解析
- run_event_hooks 多钩子反馈聚合 (拼接 + severity 取最严格)
- _merge_feedback 截断
- 反馈文本在 LLM context 中不被泄漏为空内容
"""

from __future__ import annotations

<<<<<<< HEAD
=======
import json
>>>>>>> origin/main
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

<<<<<<< HEAD
pytestmark = pytest.mark.unit
=======
pytestmark = [
    pytest.mark.unit,
    # Windows cmd.exe 不解释 shell 命令中的单引号 → -c 参数解析失败 (产品级 Windows 兼容缺口)
    pytest.mark.skipif(sys.platform == "win32", reason="hooks shell 引用在 Windows cmd.exe 下不兼容（产品缺口）"),
]
>>>>>>> origin/main

PY = sys.executable


<<<<<<< HEAD
def _hook_code(code: str) -> str:
    """把一段 Python 代码包成跨平台的 hook 命令。

    Windows 的 cmd.exe 不解析单引号, 故 -c 代码必须用双引号包裹; 而双引号内的
    单引号在 cmd.exe 与 POSIX sh 下都是字面字符, 所以代码里的字符串优先用单引号,
    两平台通用。万一代码里仍出现双引号, 按 MSVCRT 与 sh 的共同规则转义为
    反斜杠 + 引号。
    """
    esc = code.replace('"', '\\"')
    return f'{PY} -c "{esc}"'


def _hook_json(payload: dict) -> str:
    """构造只输出固定 JSON 的 hook 命令 (子进程 stdout)。

    repr() 优先产生单引号字面量; 当值本身含单引号时 repr 改用双引号, 此时由
    _hook_code 统一转义, 两种情况都跨平台可用。
    """
    lit = repr(payload)
    return _hook_code(f"import json; print(json.dumps({lit}))")

=======
>>>>>>> origin/main
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
<<<<<<< HEAD
    cmd = _hook_json(
        {
            "decision": "allow",
            "additional_context": "ruff: F401 unused import on line 5",
            "severity": "warning",
        }
=======
    cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "ruff: F401 unused import on line 5", """
        f""""severity": "warning"}}))'"""
>>>>>>> origin/main
    )
    outcome = await run_hook(_cfg(cmd), _post_payload())
    assert outcome.additional_context == "ruff: F401 unused import on line 5"
    assert outcome.severity == "warning"


@pytest.mark.asyncio()
async def test_hook_stdout_truncates_oversized_feedback():
    huge = "x" * 5000
<<<<<<< HEAD
    cmd = _hook_json({"decision": "allow", "additional_context": huge})
=======
    cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": {json.dumps(huge)}}}))'"""
    )
>>>>>>> origin/main
    outcome = await run_hook(_cfg(cmd), _post_payload())
    assert outcome.additional_context is not None
    assert len(outcome.additional_context) <= 2048 + 10  # 截断后缀


@pytest.mark.asyncio()
async def test_hook_invalid_severity_falls_back_to_info():
<<<<<<< HEAD
    cmd = _hook_json({"decision": "allow", "additional_context": "msg", "severity": "criticallll"})
=======
    cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "msg", "severity": "criticallll"}}))'"""
    )
>>>>>>> origin/main
    outcome = await run_hook(_cfg(cmd), _post_payload())
    assert outcome.severity == "info"


@pytest.mark.asyncio()
async def test_hook_feedback_on_deny_still_propagates():
<<<<<<< HEAD
    cmd = _hook_json({"decision": "deny", "reason": "blocked", "additional_context": "see docs"})
=======
    cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny", """
        f""""reason": "blocked", "additional_context": "see docs"}}))'"""
    )
>>>>>>> origin/main
    outcome = await run_hook(_cfg(cmd), _post_payload())
    assert outcome.denied
    assert outcome.additional_context == "see docs"


# ==================== 多钩子聚合 ====================


@pytest.mark.asyncio()
async def test_run_event_hooks_merges_multiple_feedbacks():
<<<<<<< HEAD
    cmd1 = _hook_json({"decision": "allow", "additional_context": "line 1: unused import"})
    cmd2 = _hook_json({"decision": "allow", "additional_context": "line 5: typo"})
=======
    cmd1 = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "line 1: unused import"}}))'"""
    )
    cmd2 = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "line 5: typo"}}))'"""
    )
>>>>>>> origin/main
    hooks = [_cfg(cmd1), _cfg(cmd2)]
    outcome = await run_event_hooks(hooks, "post_tool_use", "bash", _post_payload())
    assert outcome.has_feedback
    assert "line 1: unused import" in outcome.additional_context
    assert "line 5: typo" in outcome.additional_context


@pytest.mark.asyncio()
async def test_run_event_hooks_severity_takes_highest():
<<<<<<< HEAD
    info_cmd = _hook_json(
        {
            "decision": "allow",
            "additional_context": "info msg",
            "severity": "info",
        }
    )
    err_cmd = _hook_json(
        {
            "decision": "allow",
            "additional_context": "err msg",
            "severity": "error",
        }
    )
    warn_cmd = _hook_json(
        {
            "decision": "allow",
            "additional_context": "warn msg",
            "severity": "warning",
        }
=======
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
>>>>>>> origin/main
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
<<<<<<< HEAD
    info_cmd = _hook_json({"decision": "allow", "additional_context": "first observation"})
    deny_cmd = _hook_json({"decision": "deny", "reason": "no"})
=======
    info_cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow", """
        f""""additional_context": "first observation"}}))'"""
    )
    deny_cmd = (
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny", "reason": "no"}}))'"""
    )
>>>>>>> origin/main
    outcome = await run_event_hooks(
        [_cfg(info_cmd), _cfg(deny_cmd)], "post_tool_use", "bash", _post_payload()
    )
    assert outcome.denied
    assert outcome.additional_context == "first observation"


@pytest.mark.asyncio()
async def test_run_event_hooks_no_feedback_when_none_provided():
<<<<<<< HEAD
    cmd = _hook_json({"decision": "allow"})
=======
    cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow"}}))'"""
>>>>>>> origin/main
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
