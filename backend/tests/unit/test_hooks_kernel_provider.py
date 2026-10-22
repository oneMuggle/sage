# ruff: noqa: UP006, UP007, UP035, UP045
"""R79 单测：hook 生命周期收编 + 旧/内核双路径对照。

对照测试是本轮的验收门：同一组 ``HookConfig`` 在两套派发路径下必须产生
**逐字段相同**的 ``HookOutcome``（decision / updated_input / reason / messages /
additional_context / severity）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from backend.application.kernel.fiber import PluginHost
from backend.hooks.config import HookConfig
from backend.hooks.kernel_provider import (
    HOOKS_SERVICE_NAME,
    KERNEL_HOOKS_ENV,
    KernelHookProvider,
    fire_hooks,
    kernel_hooks_enabled,
)
from backend.hooks.runner import DECISION_ALLOW, DECISION_NOOP, run_event_hooks

# --------------------------------------------------------------------------- #
# 测试用钩子处理器（通过 hook_type="python" 的 dotted path 注入）
# --------------------------------------------------------------------------- #


async def deny_everything(payload: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    return {"decision": "deny", "reason": config.get("reason", "blocked by test hook")}


async def allow_with_feedback(
    payload: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "decision": "allow",
        "additional_context": config.get("context", "请检查命名规范"),
        "severity": config.get("severity", "warning"),
    }


async def modify_args(payload: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    return {"decision": "modify", "updated_input": {"command": "echo patched"}}


async def explode(payload: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    raise RuntimeError("handler failure must be fail-open")


_THIS_MODULE = "backend.tests.unit.test_hooks_kernel_provider"


def _py_hook(name: str, event: str = "pre_tool_use", matcher: str = "*") -> HookConfig:
    return HookConfig(
        event=event,
        matcher=matcher,
        hook_type="python",
        handler=f"{_THIS_MODULE}.{name}",
    )


PAYLOAD: Dict[str, Any] = {
    "hook_event_name": "pre_tool_use",
    "tool_name": "bash",
    "tool_input": {"command": "ls"},
}

HOOK_SETS: List[List[HookConfig]] = [
    [],
    [_py_hook("allow_with_feedback")],
    [_py_hook("deny_everything")],
    [_py_hook("modify_args")],
    [_py_hook("explode")],
    [_py_hook("allow_with_feedback"), _py_hook("deny_everything")],
    [_py_hook("modify_args"), _py_hook("deny_everything")],
    [_py_hook("allow_with_feedback"), _py_hook("allow_with_feedback")],
    # matcher 不命中 → 不执行
    [_py_hook("deny_everything", matcher="write_file")],
    # 事件不匹配 → 不执行
    [_py_hook("deny_everything", event="post_tool_use")],
]


def _outcome_tuple(outcome: Any) -> tuple:
    """把 HookOutcome 归一成可比较元组（对照测试用）。"""
    return (
        outcome.decision,
        outcome.updated_input,
        outcome.reason,
        tuple(outcome.messages),
        outcome.additional_context,
        outcome.severity,
    )


# --------------------------------------------------------------------------- #
# 生命周期
# --------------------------------------------------------------------------- #


class TestLifecycle:
    async def test_start_makes_hooks_active(self) -> None:
        provider = KernelHookProvider(PluginHost())
        assert provider.active_hooks() == []
        assert not provider.running

        await provider.start([_py_hook("allow_with_feedback")])

        assert provider.running
        assert len(provider.active_hooks()) == 1

    async def test_stop_clears_hooks_and_service(self) -> None:
        host = PluginHost()
        provider = KernelHookProvider(host)
        await provider.start([_py_hook("allow_with_feedback")])
        assert host.services.get(HOOKS_SERVICE_NAME) is provider

        await provider.stop()

        assert provider.active_hooks() == []
        assert not provider.running
        assert host.services.get(HOOKS_SERVICE_NAME) is None
        assert host.get(provider.plugin_id) is None

    async def test_reload_swaps_hook_set_without_residue(self) -> None:
        host = PluginHost()
        provider = KernelHookProvider(host)
        await provider.start([_py_hook("allow_with_feedback"), _py_hook("deny_everything")])
        assert len(provider.active_hooks()) == 2

        await provider.reload([_py_hook("modify_args")])

        assert len(provider.active_hooks()) == 1
        assert host.services.get(HOOKS_SERVICE_NAME) is provider
        # 旧的两条 deny/feedback 不应残留：此时应是 modify 结果
        outcome = await provider.dispatch("pre_tool_use", "bash", PAYLOAD)
        assert outcome.decision == "modify"
        assert outcome.updated_input == {"command": "echo patched"}

    async def test_start_is_idempotent(self) -> None:
        provider = KernelHookProvider(PluginHost())
        await provider.start([_py_hook("deny_everything")])
        await provider.start([_py_hook("deny_everything")])

        assert len(provider.active_hooks()) == 1

    async def test_dispatch_before_start_is_allow(self) -> None:
        provider = KernelHookProvider(PluginHost())
        outcome = await provider.dispatch("pre_tool_use", "bash", PAYLOAD)
        assert outcome.decision == DECISION_ALLOW

    async def test_dispatch_after_stop_is_allow(self) -> None:
        provider = KernelHookProvider(PluginHost())
        await provider.start([_py_hook("deny_everything")])
        await provider.stop()

        outcome = await provider.dispatch("pre_tool_use", "bash", PAYLOAD)
        assert outcome.decision == DECISION_ALLOW

    async def test_shutdown_disposes_host(self) -> None:
        host = PluginHost()
        provider = KernelHookProvider(host)
        await provider.start([_py_hook("deny_everything")])

        await provider.shutdown()

        assert provider.active_hooks() == []
        assert host.states() == {}

    def test_dispatch_sync_without_loop(self) -> None:
        # 必须是同步用例：async 用例本身就处于运行中的事件循环内，
        # dispatch_sync 会走 fail-open 分支（见下一条用例）。
        provider = KernelHookProvider(PluginHost())
        asyncio.run(provider.start([_py_hook("deny_everything")]))

        outcome = provider.dispatch_sync("pre_tool_use", "bash", PAYLOAD)

        assert outcome.decision == "deny"

    async def test_dispatch_sync_inside_running_loop_is_noop(self) -> None:
        provider = KernelHookProvider(PluginHost())
        await provider.start([_py_hook("deny_everything")])

        outcome = provider.dispatch_sync("pre_tool_use", "bash", PAYLOAD)  # 运行在事件循环中

        assert outcome.decision == DECISION_NOOP
        assert outcome.reason == "event loop running"


# --------------------------------------------------------------------------- #
# 对照测试（验收门）
# --------------------------------------------------------------------------- #


class TestParity:
    @pytest.mark.parametrize("hooks", HOOK_SETS, ids=[str(i) for i in range(len(HOOK_SETS))])
    async def test_kernel_path_matches_legacy_path(self, hooks: List[HookConfig]) -> None:
        legacy = await run_event_hooks(hooks, "pre_tool_use", "bash", PAYLOAD)

        provider = KernelHookProvider(PluginHost())
        await provider.start(hooks)
        kernel = await provider.dispatch("pre_tool_use", "bash", PAYLOAD)

        assert _outcome_tuple(kernel) == _outcome_tuple(legacy)

    async def test_parity_holds_after_reload(self) -> None:
        hooks = [_py_hook("allow_with_feedback"), _py_hook("modify_args")]
        provider = KernelHookProvider(PluginHost())
        await provider.start([_py_hook("deny_everything")])
        await provider.reload(hooks)

        kernel = await provider.dispatch("pre_tool_use", "bash", PAYLOAD)
        legacy = await run_event_hooks(hooks, "pre_tool_use", "bash", PAYLOAD)

        assert _outcome_tuple(kernel) == _outcome_tuple(legacy)


# --------------------------------------------------------------------------- #
# fire_hooks 开关路由
# --------------------------------------------------------------------------- #


class TestFireHooks:
    async def test_default_routes_to_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KERNEL_HOOKS_ENV, raising=False)
        calls: List[str] = []

        def loader() -> List[HookConfig]:
            calls.append("legacy")
            return [_py_hook("deny_everything")]

        provider = KernelHookProvider(PluginHost())
        await provider.start([_py_hook("allow_with_feedback")])

        outcome = await fire_hooks(
            "pre_tool_use", "bash", PAYLOAD, hooks_loader=loader, provider=provider
        )

        assert calls == ["legacy"]
        assert outcome.decision == "deny"

    async def test_flag_on_routes_to_kernel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(KERNEL_HOOKS_ENV, "1")
        calls: List[str] = []

        def loader() -> List[HookConfig]:
            calls.append("legacy")
            return [_py_hook("deny_everything")]

        provider = KernelHookProvider(PluginHost())
        await provider.start([_py_hook("allow_with_feedback")])

        outcome = await fire_hooks(
            "pre_tool_use", "bash", PAYLOAD, hooks_loader=loader, provider=provider
        )

        assert calls == []  # 内核路径不调用旧加载器
        assert outcome.decision == "allow"

    async def test_flag_on_without_provider_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(KERNEL_HOOKS_ENV, "1")

        outcome = await fire_hooks(
            "pre_tool_use",
            "bash",
            PAYLOAD,
            hooks_loader=lambda: [_py_hook("deny_everything")],
            provider=None,
        )

        assert outcome.decision == "deny"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", False),
            ("0", False),
            ("false", False),
            ("1", True),
            ("true", True),
            ("ON", True),
            (" yes ", True),
        ],
    )
    def test_flag_parsing(
        self, raw: str, expected: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if raw:
            monkeypatch.setenv(KERNEL_HOOKS_ENV, raw)
        else:
            monkeypatch.delenv(KERNEL_HOOKS_ENV, raising=False)
        assert kernel_hooks_enabled() is expected
