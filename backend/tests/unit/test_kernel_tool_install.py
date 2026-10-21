# ruff: noqa: UP006, UP007, UP035
"""R80：``backend.application.kernel.tool_install`` 的机制单测。

这一层只管编排、不认识任何具体工具，因此用只记录顺序的假注册表即可覆盖：
顺序保真 / 能力门控 / 失败策略 / 报告差集 / 开关解析。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import pytest

from backend.application.kernel.tool_install import (
    TOOL_BUNDLES_ENV,
    InstallReport,
    ToolBundle,
    ToolInstallContext,
    install_bundles,
    tool_bundles_enabled,
)


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeRegistry:
    def __init__(self) -> None:
        self.names: List[str] = []

    def register(self, tool: _FakeTool) -> None:
        self.names.append(tool.name)

    def list_names(self) -> List[str]:
        return list(self.names)


def _bundle(
    name: str,
    *tools: str,
    requires: Tuple[str, ...] = (),
    critical: bool = True,
) -> ToolBundle:
    def install(ctx: ToolInstallContext) -> None:
        for tool_name in tools:
            ctx.registry.register(_FakeTool(tool_name))

    return ToolBundle(name=name, install=install, requires=requires, critical=critical)


def _boom_bundle(name: str, *, critical: bool = True) -> ToolBundle:
    def install(ctx: ToolInstallContext) -> None:
        raise RuntimeError(f"{name} 炸了")

    return ToolBundle(name=name, install=install, critical=critical)


def _ctx(**kwargs: object) -> ToolInstallContext:
    return ToolInstallContext(registry=_FakeRegistry(), **kwargs)  # type: ignore[arg-type]


def test_installs_in_declaration_order() -> None:
    ctx = _ctx()
    bundles = [_bundle("a", "t1", "t2"), _bundle("b", "t3")]

    report = install_bundles(ctx, bundles)

    assert ctx.registry.list_names() == ["t1", "t2", "t3"]
    assert report.installed == ("t1", "t2", "t3")
    assert report.ok


def test_bundle_without_capability_is_skipped() -> None:
    ctx = _ctx(capabilities={})
    bundles = [_bundle("net", "web", requires=("network.search",)), _bundle("local", "file")]

    report = install_bundles(ctx, bundles)

    assert ctx.registry.list_names() == ["file"]
    assert report.skipped == ("net",)


def test_capability_present_installs_bundle() -> None:
    ctx = _ctx(capabilities={"network.search": True})
    report = install_bundles(ctx, [_bundle("net", "web", requires=("network.search",))])

    assert ctx.registry.list_names() == ["web"]
    assert report.skipped == ()


def test_all_required_capabilities_must_hold() -> None:
    ctx = _ctx(capabilities={"network.search": True, "network.fetch": False})
    bundles = [_bundle("net", "web", requires=("network.search", "network.fetch"))]

    report = install_bundles(ctx, bundles)

    assert ctx.registry.list_names() == []
    assert report.skipped == ("net",)


def test_empty_requires_always_enabled() -> None:
    ctx = _ctx(capabilities={})
    report = install_bundles(ctx, [_bundle("local", "file")])

    assert report.installed == ("file",)
    assert report.skipped == ()


def test_strict_raises_on_critical_bundle() -> None:
    ctx = _ctx()
    with pytest.raises(RuntimeError):
        install_bundles(ctx, [_boom_bundle("bad")], strict=True)


def test_non_critical_bundle_does_not_raise_under_strict() -> None:
    ctx = _ctx()
    report = install_bundles(ctx, [_boom_bundle("mcp", critical=False)], strict=True)

    assert report.ok is False
    assert [name for name, _ in report.failed] == ["mcp"]
    assert ctx.registry.list_names() == []


def test_lenient_mode_records_and_continues() -> None:
    ctx = _ctx()
    bundles = [_boom_bundle("bad"), _bundle("good", "t1")]

    report = install_bundles(ctx, bundles, strict=False)

    assert [name for name, _ in report.failed] == ["bad"]
    assert report.installed == ("t1",)


def test_report_installed_is_a_true_diff() -> None:
    """已注册的工具不计入 ``installed`` —— 报告反映真实落库量。"""
    ctx = _ctx()
    ctx.registry.register(_FakeTool("preexisting"))

    report = install_bundles(ctx, [_bundle("a", "preexisting", "fresh")])

    assert report.installed == ("fresh",)


def test_report_is_frozen() -> None:
    report = InstallReport(installed=("a",))
    with pytest.raises(Exception):  # noqa: B017, PT011 —— dataclass(frozen=True) 的语义检查
        report.installed = ()  # type: ignore[misc]


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", " yes ", "on"])
def test_switch_accepts_truthy(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOOL_BUNDLES_ENV, raw)
    assert tool_bundles_enabled() is True


@pytest.mark.parametrize("raw", ["", "0", "false", "off", "no", "maybe"])
def test_switch_defaults_to_legacy(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOOL_BUNDLES_ENV, raw)
    assert tool_bundles_enabled() is False


def test_switch_absent_means_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TOOL_BUNDLES_ENV, raising=False)
    assert tool_bundles_enabled() is False


def test_install_order_matches_bundle_sequence() -> None:
    """反向声明顺序必须原样反映到注册顺序（不做排序/去重）。"""
    ctx = _ctx()
    bundles: Sequence[ToolBundle] = [_bundle("b", "t2"), _bundle("a", "t1")]

    install_bundles(ctx, bundles)

    assert ctx.registry.list_names() == ["t2", "t1"]
