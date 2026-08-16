"""
M6 Hooks 子系统单元测试

覆盖 runner payload/decision 解析 (allow/deny/modify)、超时 → no-op、
非 JSON → no-op、deny 生效、matcher glob、配置校验。
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from backend.hooks.config import (
    DEFAULT_TIMEOUT_SECONDS,
    HookConfig,
    HookConfigError,
    load_hooks,
    validate_hooks,
)
from backend.hooks.runner import (
    DECISION_ALLOW,
    DECISION_NOOP,
    build_payload,
    matches_tool,
    run_event_hooks,
    run_hook,
    validate_modified_args,
)

pytestmark = pytest.mark.unit

PY = sys.executable


def _cfg(command: str, event: str = "pre_tool_use", matcher: str = "*", timeout: float = 5.0):
    return HookConfig(event=event, command=command, matcher=matcher, timeout_seconds=timeout)


def _payload(tool_name: str = "terminal", event: str = "pre_tool_use") -> Dict[str, Any]:
    return build_payload(event, tool_name, {"command": "ls"})


# ==================== decision 解析 ====================


@pytest.mark.asyncio()
async def test_allow_decision_parsed():
    cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow"}}))'"""
    outcome = await run_hook(_cfg(cmd), _payload())
    assert outcome.decision == DECISION_ALLOW
    assert not outcome.denied


@pytest.mark.asyncio()
async def test_deny_decision_honored_with_reason():
    cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny", "reason": "nope"}}))'"""
    outcome = await run_hook(_cfg(cmd), _payload())
    assert outcome.denied
    assert outcome.reason == "nope"


@pytest.mark.asyncio()
async def test_modify_decision_carries_updated_input():
    cmd = (
        f"""{PY} -c 'import json; """
        f"""print(json.dumps({{"decision": "modify", "updated_input": {{"command": "echo hi"}}}}))'"""
    )
    outcome = await run_hook(_cfg(cmd), _payload())
    assert outcome.modified
    assert outcome.updated_input == {"command": "echo hi"}


@pytest.mark.asyncio()
async def test_modify_without_updated_input_is_noop():
    cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "modify"}}))'"""
    outcome = await run_hook(_cfg(cmd), _payload())
    assert outcome.decision == DECISION_NOOP
    assert not outcome.modified


@pytest.mark.asyncio()
async def test_unknown_decision_is_noop():
    cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "explode"}}))'"""
    outcome = await run_hook(_cfg(cmd), _payload())
    assert outcome.decision == DECISION_NOOP


# ==================== fail-open 路径 ====================


@pytest.mark.asyncio()
async def test_timeout_kills_process_and_is_noop():
    outcome_started = time.monotonic()
    outcome = await run_hook(_cfg("sleep 30", timeout=0.3), _payload())
    elapsed = time.monotonic() - outcome_started
    assert outcome.decision == DECISION_NOOP
    assert outcome.reason == "timeout"
    assert elapsed < 10, "timeout should kill the process group promptly"


@pytest.mark.asyncio()
async def test_nonzero_exit_is_noop():
    outcome = await run_hook(_cfg("exit 3"), _payload())
    assert outcome.decision == DECISION_NOOP
    assert "3" in (outcome.reason or "")


@pytest.mark.asyncio()
async def test_non_json_stdout_is_noop():
    outcome = await run_hook(_cfg("echo hello-not-json"), _payload())
    assert outcome.decision == DECISION_NOOP
    assert outcome.reason == "non-json stdout"


@pytest.mark.asyncio()
async def test_empty_stdout_is_silent_allow():
    outcome = await run_hook(_cfg("true"), _payload())
    assert outcome.decision == DECISION_ALLOW


@pytest.mark.asyncio()
async def test_env_vars_and_stdin_payload_reach_hook():
    cmd = (
        f"""{PY} -c 'import json, os, sys; p = json.load(sys.stdin); """
        f"""print(json.dumps({{"decision": "deny", "reason": """
        f"""os.environ["SAGE_HOOK_EVENT"] + "/" + os.environ["SAGE_TOOL_NAME"] + "/" """
        f"""+ p["tool_name"]}}))'"""
    )
    outcome = await run_hook(_cfg(cmd), _payload(tool_name="terminal"))
    assert outcome.denied
    assert outcome.reason == "pre_tool_use/terminal/terminal"


# ==================== matcher glob ====================


@pytest.mark.parametrize(
    ("matcher", "tool", "expected"),
    [
        ("*", "terminal", True),
        ("*", "file_read", True),
        ("term*", "terminal", True),
        ("term*", "file_read", False),
        ("file_*", "file_read", True),
        ("file_*", "terminal", False),
        ("terminal", "terminal", True),
    ],
)
def test_matcher_globbing(matcher: str, tool: str, expected: bool):
    assert matches_tool(matcher, tool) is expected


@pytest.mark.asyncio()
async def test_run_event_hooks_skips_non_matching():
    deny = _cfg(
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny"}}))'""",
        matcher="other_*",
    )
    outcome = await run_event_hooks([deny], "pre_tool_use", "terminal", _payload())
    assert outcome.decision == DECISION_ALLOW


@pytest.mark.asyncio()
async def test_run_event_hooks_deny_short_circuits():
    deny_cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny", "reason": "first"}}))'"""
    allow_cmd = f"""{PY} -c 'import json; print(json.dumps({{"decision": "allow"}}))'"""
    hooks = [_cfg(deny_cmd), _cfg(allow_cmd)]
    outcome = await run_event_hooks(hooks, "pre_tool_use", "terminal", _payload())
    assert outcome.denied
    assert outcome.reason == "first"


@pytest.mark.asyncio()
async def test_run_event_hooks_filters_by_event():
    deny = _cfg(
        f"""{PY} -c 'import json; print(json.dumps({{"decision": "deny"}}))'""",
        event="post_tool_use",
    )
    outcome = await run_event_hooks([deny], "pre_tool_use", "terminal", _payload())
    assert outcome.decision == DECISION_ALLOW


# ==================== payload / schema 再校验 ====================


def test_build_payload_pre_vs_post():
    pre = build_payload("pre_tool_use", "terminal", {"command": "ls"})
    assert pre == {
        "hook_event_name": "pre_tool_use",
        "tool_name": "terminal",
        "tool_input": {"command": "ls"},
    }
    post = build_payload("post_tool_use", "terminal", {"command": "ls"}, tool_output="ok", is_error=False)
    assert post["tool_output"] == "ok"
    assert post["tool_result_is_error"] is False


def test_validate_modified_args_required_and_unknown():
    schema = {
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    }
    assert validate_modified_args({"expression": "1+1"}, schema) is None
    assert "missing required" in (validate_modified_args({}, schema) or "")
    assert "unknown" in (validate_modified_args({"expression": "1", "junk": 2}, schema) or "")
    # 无 schema → 放行
    assert validate_modified_args({"anything": 1}, None) is None


# ==================== 配置校验 ====================


def test_config_validation_accepts_defaults():
    hooks = validate_hooks([{"event": "pre_tool_use", "command": "echo hi"}])
    assert len(hooks) == 1
    assert hooks[0].matcher == "*"
    assert hooks[0].timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_config_validation_rejects_unknown_event():
    with pytest.raises(HookConfigError, match="event"):
        validate_hooks([{"event": "mid_tool_use", "command": "echo hi"}])


def test_config_validation_rejects_empty_command():
    with pytest.raises(HookConfigError, match="command"):
        validate_hooks([{"event": "pre_tool_use", "command": "   "}])


def test_config_validation_rejects_non_list():
    with pytest.raises(HookConfigError, match="JSON list"):
        validate_hooks({"event": "pre_tool_use", "command": "x"})


def test_config_validation_caps_at_20_hooks():
    raw = [{"event": "pre_tool_use", "command": "true"} for _ in range(21)]
    with pytest.raises(HookConfigError, match="too many hooks"):
        validate_hooks(raw)
    assert len(validate_hooks(raw[:20])) == 20


def test_load_hooks_fail_open_on_invalid_config():
    repo = MagicMock()
    repo.get_json.return_value = [{"event": "bogus", "command": "x"}]
    assert load_hooks(repo) == []


def test_load_hooks_fail_open_on_repo_error():
    repo = MagicMock()
    repo.get_json.side_effect = RuntimeError("db down")
    assert load_hooks(repo) == []


def test_load_hooks_returns_valid_configs():
    repo = MagicMock()
    repo.get_json.return_value = [
        {"event": "post_tool_use", "command": "echo done", "matcher": "file_*"},
    ]
    hooks = load_hooks(repo)
    assert len(hooks) == 1
    assert hooks[0].event == "post_tool_use"
    assert hooks[0].matcher == "file_*"


# ---------------------------------------------------------------------------
# 审查加固回归 (M6 review)
# ---------------------------------------------------------------------------


def test_config_validation_rejects_timeout_above_max():
    """timeout_seconds > 300 → 拒绝 (20 条钩子串行, 病态配置可拖死循环)。"""
    with pytest.raises(HookConfigError):
        validate_hooks(
            [{"event": "pre_tool_use", "command": "echo hi", "timeout_seconds": 301}]
        )


def test_config_validation_accepts_timeout_at_max():
    hooks = validate_hooks(
        [{"event": "pre_tool_use", "command": "echo hi", "timeout_seconds": 300}]
    )
    assert hooks[0].timeout_seconds == 300.0


def test_build_payload_truncates_oversized_tool_output():
    """post_tool_use payload 的 tool_output 截断至 PAYLOAD_OUTPUT_CAP。"""
    from backend.hooks.runner import PAYLOAD_OUTPUT_CAP

    payload = build_payload(
        "post_tool_use",
        "read_file",
        {"path": "big.txt"},
        tool_output="x" * (PAYLOAD_OUTPUT_CAP + 5000),
    )
    assert len(payload["tool_output"]) <= PAYLOAD_OUTPUT_CAP + 16
    assert payload["tool_output"].endswith("…[截断]")
