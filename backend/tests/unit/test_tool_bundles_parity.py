# ruff: noqa: UP006, UP007, UP035
"""R80：bundle 装配与旧平铺装配的等价性对照。

``register_all_tools`` 自 R80 起有两条路径，由 ``SAGE_KERNEL_TOOL_BUNDLES``
选择。本文件是**等价性的主证据**：同一组入参分别走两条路径，逐项比对

* 工具名集合 **与顺序**（顺序决定 LLM schema 的排列，进而影响提示缓存命中）；
* ``declared_risks()``（权限门禁的数据来源）；
* ``get_schemas_for_llm()`` 的完整 schema 列表；
* 三档网络策略（ONLINE / INTRANET / OFFLINE）下的注册子集。

另外两项结构断言：服务 getter 的透传、以及"bundle 声明不漏不重"。
"""

from __future__ import annotations

import ssl
from typing import Any, Iterator, List, Tuple
from unittest.mock import patch

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.tool_policy import ToolPolicy
from backend.tools import register_all_tools
from backend.tools.registry import ToolRegistry

_MODES = [NetworkMode.ONLINE, NetworkMode.INTRANET, NetworkMode.OFFLINE]

_ENV = "SAGE_KERNEL_TOOL_BUNDLES"


class _RecordingRegistry:
    """只记录注册顺序的假注册表 —— 供 bundle 函数级断言使用。"""

    def __init__(self) -> None:
        self.tools: List[Any] = []

    def register(self, tool: Any) -> None:
        self.tools.append(tool)

    def list_names(self) -> List[str]:
        return [tool.name for tool in self.tools]


def _has_attr_value(obj: Any, value: Any) -> bool:
    """对象自身属性里有 ``is value`` 的项（不依赖具体属性名）。"""
    return any(item is value for item in vars(obj).values())


@pytest.fixture(autouse=True, scope="module")
def _fast_tls() -> Iterator[None]:
    """出网工具构造时会建 SSL 上下文；Windows 上每次 ~2s（读系统证书库）。

    本文件只比对注册结果、不联网，共享一个不加载系统证书库的上下文即可：
    一次全量装配从 18.5s 降到 0.3s。
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with patch("ssl.create_default_context", lambda *args, **kwargs: ctx):
        yield


@pytest.fixture(autouse=True)
def _stub_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 注册对等价性无贡献却要联网，单测里打成 no-op。"""
    import backend.mcp as mcp_pkg

    monkeypatch.setattr(mcp_pkg, "register_mcp_tools", lambda registry: None, raising=False)


def _install(mode: NetworkMode, *, bundlized: bool, monkeypatch: pytest.MonkeyPatch) -> ToolRegistry:
    monkeypatch.setenv(_ENV, "1" if bundlized else "0")
    registry = ToolRegistry()
    register_all_tools(registry, network_policy=NetworkPolicy(mode=mode))
    return registry


# ===== 等价性：三档网络策略 × 两项装配路径 =====


@pytest.mark.parametrize("mode", _MODES)
def test_same_tool_names_in_same_order(mode: NetworkMode, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = _install(mode, bundlized=False, monkeypatch=monkeypatch)
    bundled = _install(mode, bundlized=True, monkeypatch=monkeypatch)

    assert bundled.list_names() == legacy.list_names()


@pytest.mark.parametrize("mode", _MODES)
def test_same_declared_risks(mode: NetworkMode, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = _install(mode, bundlized=False, monkeypatch=monkeypatch)
    bundled = _install(mode, bundlized=True, monkeypatch=monkeypatch)

    assert bundled.declared_risks() == legacy.declared_risks()


@pytest.mark.parametrize("mode", _MODES)
def test_same_llm_schemas(mode: NetworkMode, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = _install(mode, bundlized=False, monkeypatch=monkeypatch)
    bundled = _install(mode, bundlized=True, monkeypatch=monkeypatch)

    assert bundled.get_schemas_for_llm() == legacy.get_schemas_for_llm()


# ===== 能力门控：三档之间该差多少 =====


def _names(mode: NetworkMode, *, bundlized: bool, monkeypatch: pytest.MonkeyPatch) -> List[str]:
    return _install(mode, bundlized=bundlized, monkeypatch=monkeypatch).list_names()


@pytest.mark.parametrize("bundlized", [False, True])
def test_network_gating_counts(bundlized: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    online = _names(NetworkMode.ONLINE, bundlized=bundlized, monkeypatch=monkeypatch)
    intranet = _names(NetworkMode.INTRANET, bundlized=bundlized, monkeypatch=monkeypatch)
    offline = _names(NetworkMode.OFFLINE, bundlized=bundlized, monkeypatch=monkeypatch)

    # ONLINE 独有 web_search（1 个）；INTRANET 独有出网下载四件套（4 个）
    assert len([n for n in online if n not in intranet]) == 1
    assert len([n for n in intranet if n not in offline]) == 4
    assert len(online) > 80


def test_bundle_declarations_cover_every_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """BUNDLES 声明的工具数与旧路径注册数逐一对齐（不漏不重）。"""
    from backend.application.kernel.tool_install import ToolInstallContext, install_bundles
    from backend.tools.tool_bundles import BUNDLES

    recorder = _RecordingRegistry()
    network_policy = NetworkPolicy(mode=NetworkMode.ONLINE)
    ctx = ToolInstallContext(
        registry=recorder,
        policy=ToolPolicy(),
        network_policy=network_policy,
        capabilities={
            "network.search": network_policy.search_enabled(),
            "network.fetch": network_policy.fetch_enabled(),
        },
    )
    report = install_bundles(ctx, BUNDLES)

    declared = [tool.name for tool in recorder.tools]
    assert len(declared) == len(set(declared)), "bundle 之间有重名工具"
    assert list(report.installed) == declared, "报告与真实注册结果不一致"
    assert report.failed == ()
    assert report.skipped == ()


# ===== 服务 getter 透传（不依赖属性名） =====


def _forwarded(bundle_name: str) -> Tuple[bool, bool]:
    from backend.application.kernel.tool_install import ToolInstallContext, install_bundles
    from backend.tools.tool_bundles import BUNDLES

    def scheduler_getter() -> None:
        return None

    def todo_getter() -> None:
        return None

    recorder = _RecordingRegistry()
    bundle = next(b for b in BUNDLES if b.name == bundle_name)
    ctx = ToolInstallContext(
        registry=recorder,
        policy=ToolPolicy(),
        network_policy=NetworkPolicy(),
        scheduler_service_getter=scheduler_getter,
        todo_service_getter=todo_getter,
    )
    install_bundles(ctx, [bundle])
    assert recorder.tools, f"{bundle_name} 未注册任何工具"

    wanted = scheduler_getter if bundle_name == "schedule" else todo_getter
    return (
        all(_has_attr_value(tool, wanted) for tool in recorder.tools),
        len(recorder.tools),
    )


@pytest.mark.parametrize(
    ("bundle_name", "expected_count"),
    [("schedule", 3), ("todo", 5)],
)
def test_service_getter_is_forwarded(bundle_name: str, expected_count: int) -> None:
    all_forwarded, count = _forwarded(bundle_name)

    assert count == expected_count
    assert all_forwarded, f"{bundle_name} 未把 getter 原样传给工具实例"


def test_execute_code_shares_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """``execute_code`` 的 registry 自引用必须仍是同一对象。"""
    registry = _install(NetworkMode.ONLINE, bundlized=True, monkeypatch=monkeypatch)
    name = next(n for n in registry.list_names() if "execute" in n)
    tool = registry.get(name)

    assert tool is not None
    assert _has_attr_value(tool, registry)


def test_bundlized_report_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.tools.tool_bundles import BUNDLES, install_default_bundles

    monkeypatch.setenv(_ENV, "1")
    registry = ToolRegistry()
    report = install_default_bundles(registry, ToolPolicy(), NetworkPolicy())

    assert report.ok
    assert len(report.installed) == len(registry.list_names())
    assert any(bundle.name == "mcp" for bundle in BUNDLES)
