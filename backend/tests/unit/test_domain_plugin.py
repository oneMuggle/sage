# ruff: noqa: UP006, UP007, UP035, UP045
"""契约层单测：枚举、能力声明、校验器（R78）。"""

from __future__ import annotations

import dataclasses

import pytest

from backend.domain.plugin import (
    CapabilityDecl,
    FiberState,
    PluginContractError,
    ProviderKind,
    TrustLevel,
    validate_capability_name,
    validate_plugin_id,
    validate_version,
)


class TestEnums:
    def test_provider_kind_values(self) -> None:
        assert {kind.value for kind in ProviderKind} == {
            "tool",
            "skill",
            "hook",
            "command",
            "mcp",
            "service",
            "ui",
            "agent",
        }

    def test_trust_level_values(self) -> None:
        assert {level.value for level in TrustLevel} == {"builtin", "verified", "personal"}

    def test_fiber_state_classification(self) -> None:
        assert FiberState.LOADING.is_running
        assert FiberState.ACTIVE.is_running
        assert not FiberState.PENDING.is_running
        assert FiberState.FAILED.is_terminal
        assert FiberState.DISPOSED.is_terminal
        assert not FiberState.ACTIVE.is_terminal


class TestCapabilityDecl:
    def test_valid_declaration(self) -> None:
        decl = CapabilityDecl(plugin_id="my-plugin", kind=ProviderKind.TOOL, name="greet")
        assert decl.qualified_name == "my-plugin/greet"
        assert decl.version == "1.0.0"
        assert decl.description == ""

    def test_matches_by_kind_and_name(self) -> None:
        decl = CapabilityDecl(plugin_id="p", kind=ProviderKind.HOOK, name="audit")
        assert decl.matches(kind=ProviderKind.HOOK)
        assert decl.matches(name="audit")
        assert not decl.matches(kind=ProviderKind.TOOL)
        assert not decl.matches(name="other")

    def test_frozen(self) -> None:
        decl = CapabilityDecl(plugin_id="p", kind=ProviderKind.TOOL, name="t")
        with pytest.raises(dataclasses.FrozenInstanceError):
            decl.name = "other"  # type: ignore[misc]

    def test_invalid_plugin_id(self) -> None:
        with pytest.raises(PluginContractError):
            CapabilityDecl(plugin_id="Bad Id", kind=ProviderKind.TOOL, name="t")

    def test_invalid_kind(self) -> None:
        with pytest.raises(PluginContractError):
            CapabilityDecl(plugin_id="p", kind="tool", name="t")  # type: ignore[arg-type]

    def test_invalid_version(self) -> None:
        with pytest.raises(PluginContractError):
            CapabilityDecl(plugin_id="p", kind=ProviderKind.TOOL, name="t", version="1.0")


class TestValidators:
    @pytest.mark.parametrize("value", ["a", "my-plugin", "plugin_2", "acme.tools.v1", "p-1.2"])
    def test_valid_plugin_ids(self, value: str) -> None:
        assert validate_plugin_id(value) == value

    @pytest.mark.parametrize("value", ["", "-lead", "trail-", "UPPER", "has space", "a" * 101])
    def test_invalid_plugin_ids(self, value: str) -> None:
        with pytest.raises(PluginContractError):
            validate_plugin_id(value)

    @pytest.mark.parametrize("value", ["greet", "Tool_1", "web.search-v2"])
    def test_valid_capability_names(self, value: str) -> None:
        assert validate_capability_name(value) == value

    @pytest.mark.parametrize("value", ["", "-x", "x/", "has space", "a" * 101])
    def test_invalid_capability_names(self, value: str) -> None:
        with pytest.raises(PluginContractError):
            validate_capability_name(value)

    @pytest.mark.parametrize("value", ["1.0.0", "0.4.9-alpha.57", "2.0.0+build.5"])
    def test_valid_versions(self, value: str) -> None:
        assert validate_version(value) == value

    @pytest.mark.parametrize("value", ["1.0", "v1.0.0", "", "1.0.0.0"])
    def test_invalid_versions(self, value: str) -> None:
        with pytest.raises(PluginContractError):
            validate_version(value)
