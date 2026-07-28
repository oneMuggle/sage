"""Hook 执行器 (M6 生态扩展): 在工具调用前后执行用户自定义 shell 钩子。

协议 (改编自 claw-code ``runtime/src/hooks.rs``):

- 钩子命令从 STDIN 收一个 JSON payload;
- 环境变量携带 ``SAGE_HOOK_EVENT`` 与 ``SAGE_TOOL_NAME``;
- 钩子可在 STDOUT 打印一个 JSON 对象::

    {"decision": "allow" | "deny" | "modify",
     "updated_input": {...},   # 仅 "modify"
     "reason": "..."}          # 可选

**Fail-open 契约**: 超时 / 非零退出 / 非 JSON 输出 / 启动失败一律降级为
no-op (记 warning)。唯有显式 ``{"decision": "deny"}`` 会阻断工具执行。
超时杀掉整个进程组 (``start_new_session`` + ``os.killpg``; Windows 上
尽力而为)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

from backend.hooks.config import HookConfig

logger = logging.getLogger(__name__)

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_MODIFY = "modify"
DECISION_NOOP = "noop"  # 内部: 钩子故障 / 输出不可执行 → 当作没发生


@dataclass
class HookOutcome:
    """单个事件 + 工具上所有匹配钩子的合并结果。"""

    decision: str = DECISION_ALLOW
    updated_input: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    messages: List[str] = field(default_factory=list)

    @property
    def denied(self) -> bool:
        return self.decision == DECISION_DENY

    @property
    def modified(self) -> bool:
        return self.decision == DECISION_MODIFY and self.updated_input is not None


def matches_tool(matcher: str, tool_name: str) -> bool:
    """glob 匹配钩子 matcher 与工具名 (``*`` 匹配全部)。"""
    return fnmatch(tool_name, matcher or "*")


#: post_tool_use payload 中 tool_output 的截断上限 (审查加固: 工具结果
#: 可达数 MB, 逐钩子序列化全量既浪费又可能压垮钩子进程 stdin)
PAYLOAD_OUTPUT_CAP = 65536


def build_payload(
    event: str,
    tool_name: str,
    tool_input: Any,
    tool_output: Optional[str] = None,
    is_error: bool = False,
) -> Dict[str, Any]:
    """构造经 STDIN 传给钩子的 JSON payload。"""
    payload: Dict[str, Any] = {
        "hook_event_name": event,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if event == "post_tool_use":
        capped_output = tool_output
        if isinstance(capped_output, str) and len(capped_output) > PAYLOAD_OUTPUT_CAP:
            capped_output = capped_output[:PAYLOAD_OUTPUT_CAP] + "…[截断]"
        payload["tool_output"] = capped_output
        payload["tool_result_is_error"] = is_error
    return payload


def validate_modified_args(
    updated_input: Dict[str, Any],
    schema_parameters: Optional[Dict[str, Any]],
) -> Optional[str]:
    """对钩子修改后的工具参数做轻量 JSON-Schema 再校验。

    失败返回错误描述字符串, 通过返回 ``None``。只检查 ``required`` 存在性
    与未声明属性 — 深度类型校验仍由工具自身负责。无 schema 可对照时直接
    放行 (让工具自己报错)。
    """
    if not isinstance(updated_input, dict):
        return "updated_input is not an object"
    if not isinstance(schema_parameters, dict):
        return None
    required = schema_parameters.get("required") or []
    if isinstance(required, list):
        missing = [key for key in required if key not in updated_input]
        if missing:
            return f"missing required arguments: {missing}"
    properties = schema_parameters.get("properties")
    if isinstance(properties, dict):
        unknown = [key for key in updated_input if key not in properties]
        if unknown:
            return f"unknown arguments: {unknown}"
    return None


def _kill_process_group(proc: Optional[asyncio.subprocess.Process]) -> None:
    """杀掉钩子进程组 (超时兜底)。POSIX 用 killpg, Windows 尽力 kill。"""
    if proc is None or proc.returncode is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover — Windows 兜底
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError) as exc:
        logger.debug("hooks: process group kill best-effort failed: %s", exc)


def _parse_decision_dict(data: Dict[str, Any]) -> HookOutcome:
    """把钩子输出的 JSON 对象映射为 HookOutcome (未知 decision → no-op)。"""
    reason = data.get("reason")
    if not isinstance(reason, str):
        reason = None
    decision = data.get("decision", DECISION_ALLOW)

    if decision == DECISION_DENY:
        return HookOutcome(decision=DECISION_DENY, reason=reason or "denied by hook")
    if decision == DECISION_MODIFY:
        updated = data.get("updated_input")
        if isinstance(updated, dict):
            return HookOutcome(decision=DECISION_MODIFY, updated_input=updated, reason=reason)
        logger.warning("hooks: modify without object updated_input ignored (fail-open)")
        return HookOutcome(decision=DECISION_NOOP, reason="modify without updated_input")
    if decision == DECISION_ALLOW:
        return HookOutcome(decision=DECISION_ALLOW, reason=reason)
    logger.warning("hooks: unknown decision %r ignored (fail-open)", decision)
    return HookOutcome(decision=DECISION_NOOP, reason=f"unknown decision: {decision!r}")


def _parse_stdout(stdout_text: str) -> HookOutcome:
    """解析钩子 STDOUT。非 JSON 输出 → no-op (fail-open)。"""
    text = (stdout_text or "").strip()
    if not text:
        return HookOutcome(decision=DECISION_ALLOW)
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        logger.warning("hooks: non-JSON stdout ignored (fail-open): %.200r", text)
        return HookOutcome(decision=DECISION_NOOP, reason="non-json stdout")
    if not isinstance(data, dict):
        logger.warning("hooks: non-object JSON stdout ignored (fail-open): %.200r", text)
        return HookOutcome(decision=DECISION_NOOP, reason="non-object json stdout")
    return _parse_decision_dict(data)


async def run_hook(hook_cfg: HookConfig, payload_dict: Dict[str, Any]) -> HookOutcome:
    """执行单个钩子命令。永不抛异常 (任何失败 → no-op)。

    Args:
        hook_cfg: 已校验的钩子配置
        payload_dict: 经 STDIN 传入的 JSON payload

    Returns:
        HookOutcome: allow / deny / modify / noop 之一
    """
    env = os.environ.copy()
    env["SAGE_HOOK_EVENT"] = str(payload_dict.get("hook_event_name", hook_cfg.event))
    env["SAGE_TOOL_NAME"] = str(payload_dict.get("tool_name", ""))
    try:
        payload_bytes = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        logger.warning("hooks: unserializable payload, skipping hook: %s", exc)
        return HookOutcome(decision=DECISION_NOOP, reason="payload not serializable")

    proc: Optional[asyncio.subprocess.Process] = None
    try:
        proc = await asyncio.create_subprocess_shell(
            hook_cfg.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        stdout_b, _stderr_b = await asyncio.wait_for(
            proc.communicate(input=payload_bytes),
            timeout=hook_cfg.timeout_seconds,
        )
    except asyncio.TimeoutError:  # noqa: UP041 — py3.8 上不是 builtin TimeoutError 别名
        _kill_process_group(proc)
        logger.warning(
            "hooks: %s hook timed out after %.1fs (fail-open): %.120s",
            hook_cfg.event,
            hook_cfg.timeout_seconds,
            hook_cfg.command,
        )
        return HookOutcome(decision=DECISION_NOOP, reason="timeout")
    except Exception as exc:
        _kill_process_group(proc)
        logger.warning("hooks: failed to run %r (fail-open): %s", hook_cfg.command, exc)
        return HookOutcome(decision=DECISION_NOOP, reason=f"spawn error: {exc}")

    if proc.returncode != 0:
        logger.warning(
            "hooks: %s hook exited %s (fail-open): %.120s",
            hook_cfg.event,
            proc.returncode,
            hook_cfg.command,
        )
        return HookOutcome(decision=DECISION_NOOP, reason=f"exit code {proc.returncode}")

    return _parse_stdout(stdout_b.decode("utf-8", "replace"))


async def run_event_hooks(
    hooks: List[HookConfig],
    event: str,
    tool_name: str,
    payload: Dict[str, Any],
) -> HookOutcome:
    """按列表顺序执行所有匹配 ``event`` + ``tool_name`` 的钩子。

    - ``deny`` 立即短路返回;
    - 第一个有效 ``modify`` 生效 (后续钩子仍执行, 但不再覆盖参数);
    - 钩子故障是 no-op, 不影响合并结果。
    """
    merged = HookOutcome(decision=DECISION_ALLOW)
    for cfg in hooks:
        if cfg.event != event or not matches_tool(cfg.matcher, tool_name):
            continue
        outcome = await run_hook(cfg, payload)
        merged.messages.extend(outcome.messages)
        if outcome.denied:
            outcome.messages = merged.messages
            return outcome
        if outcome.modified and not merged.modified:
            merged = HookOutcome(
                decision=DECISION_MODIFY,
                updated_input=outcome.updated_input,
                reason=outcome.reason,
                messages=merged.messages,
            )
    return merged
