"""Zotero 对 LLM 可见性的回归测试（2026-10-27 feat/zotero-llm-visible）。

覆盖四层根因中的前三层：

1. 白名单：``mcp__*`` / ``mcp__<server>__*`` 受限通配 + primary 种子；
2. DB 路径：settings_repo 优先、env 兜底、异常降级；
3. prompt 注入门：注册表出现 ``mcp__zotero__*`` 才注入能力说明。

索引层（第四层）见 M2 的 ``test_zotero_ingest.py``。
"""

from __future__ import annotations

import pytest

from backend.agents import profiles
from backend.core import zotero_prompt
from backend.domain.tool_names import (
    is_mcp_tool_name,
    is_mcp_tool_reference,
    is_mcp_tool_wildcard,
    mcp_tool_wildcard_prefix,
    tool_name_in_allowlist,
)
from backend.zotero import paths as zotero_paths

# ---------------------------------------------------------------------------
# 形状识别
# ---------------------------------------------------------------------------


class TestMcpToolNameShape:
    @pytest.mark.parametrize(
        "name",
        [
            "mcp__zotero__zotero_search",
            "mcp__drawio__render_diagram",
            "mcp__my-server__do_thing",
        ],
    )
    def test_valid_names(self, name):
        assert is_mcp_tool_name(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "mcp__",
            "mcp__zotero",
            "mcp__zotero__",
            "mcp__zotero__*",
            "mcpx__zotero__tool",
            "mcp__zot ero__tool",
            "MCP__zotero__tool",
        ],
    )
    def test_invalid_names(self, name):
        assert is_mcp_tool_name(name) is False

    @pytest.mark.parametrize(
        ("entry", "prefix"),
        [
            ("mcp__*", "mcp__"),
            ("mcp__zotero__*", "mcp__zotero__"),
        ],
    )
    def test_wildcard_prefix(self, entry, prefix):
        assert mcp_tool_wildcard_prefix(entry) == prefix
        assert is_mcp_tool_wildcard(entry) is True

    @pytest.mark.parametrize(
        "entry",
        ["mcp__zot*", "mcp__*__*", "mcp__zor tero__*", "mcp__", "plugin__*"],
    )
    def test_bad_wildcards_rejected(self, entry):
        assert is_mcp_tool_wildcard(entry) is False

    def test_reference_accepts_exact_and_wildcard(self):
        assert is_mcp_tool_reference("mcp__zotero__zotero_search") is True
        assert is_mcp_tool_reference("mcp__zotero__*") is True
        assert is_mcp_tool_reference("read_file") is False


# ---------------------------------------------------------------------------
# 白名单匹配
# ---------------------------------------------------------------------------


class TestAllowlist:
    def test_global_wildcard_allows_any_server(self):
        allowed = ["mcp__*"]
        assert tool_name_in_allowlist("mcp__zotero__zotero_search", allowed)
        assert tool_name_in_allowlist("mcp__drawio__render_diagram", allowed)

    def test_server_wildcard_is_scoped(self):
        allowed = ["mcp__zotero__*"]
        assert tool_name_in_allowlist("mcp__zotero__zotero_search", allowed)
        assert not tool_name_in_allowlist("mcp__drawio__render_diagram", allowed)

    def test_exact_mcp_name(self):
        allowed = ["mcp__zotero__zotero_search"]
        assert tool_name_in_allowlist("mcp__zotero__zotero_search", allowed)
        assert not tool_name_in_allowlist("mcp__zotero__zotero_get_item", allowed)

    @pytest.mark.parametrize("entry", ["mcp__zot*", "mcp__*__*", "mcp__zotero"])
    def test_invalid_wildcards_fail_closed(self, entry):
        assert not tool_name_in_allowlist("mcp__zotero__zotero_search", [entry])

    def test_builtin_names_still_match(self):
        assert tool_name_in_allowlist("read_file", ["read_file"])
        assert not tool_name_in_allowlist("read_file", ["mcp__*"])

    def test_plugin_wildcard_unaffected(self):
        assert tool_name_in_allowlist(
            "plugin__demo__cap", ["plugin__*"], plugin_name="demo"
        )
        assert not tool_name_in_allowlist(
            "plugin__demo__cap", ["mcp__*"], plugin_name="demo"
        )


class TestPrimarySeed:
    def test_primary_seed_contains_mcp_wildcard(self):
        assert "mcp__*" in profiles._PRIMARY_SEED_TOOLS

    def test_validate_accepts_mcp_references(self):
        class _Repo:
            def list_all(self):
                return [
                    {
                        "id": "primary",
                        "tools": ["mcp__*", "mcp__zotero__zotero_search"],
                    }
                ]

        assert profiles.validate_profile_tools(repo=_Repo()) == 0

    def test_validate_still_warns_on_typo(self):
        class _Repo:
            def list_all(self):
                return [{"id": "broken", "tools": ["red_file"]}]

        assert profiles.validate_profile_tools(repo=_Repo()) == 1


# ---------------------------------------------------------------------------
# DB 路径解析（单一来源）
# ---------------------------------------------------------------------------


class TestDbPathResolution:
    def _patch_repo(self, monkeypatch, behaviour):
        from backend.data import settings_repo

        class _FakeRepo:
            def get(self, key):
                return behaviour(key)

        monkeypatch.setattr(settings_repo, "SettingsRepository", _FakeRepo)

    def test_settings_wins_over_env(self, monkeypatch):
        self._patch_repo(monkeypatch, lambda key: "/synthetic/Zotero/zotero.sqlite")
        monkeypatch.setenv("ZOTERO_DB_PATH", "/env/path.sqlite")
        assert (
            zotero_paths.resolve_zotero_db_path()
            == "/synthetic/Zotero/zotero.sqlite"
        )

    def test_env_used_when_settings_empty(self, monkeypatch):
        self._patch_repo(monkeypatch, lambda key: None)
        monkeypatch.setenv("ZOTERO_DB_PATH", "/env/path.sqlite")
        assert zotero_paths.resolve_zotero_db_path() == "/env/path.sqlite"

    def test_settings_error_degrades_to_env(self, monkeypatch):
        def _boom(key):
            raise RuntimeError("settings unavailable")

        self._patch_repo(monkeypatch, _boom)
        monkeypatch.setenv("ZOTERO_DB_PATH", "/env/path.sqlite")
        assert zotero_paths.resolve_zotero_db_path() == "/env/path.sqlite"

    def test_nothing_configured_returns_empty(self, monkeypatch):
        self._patch_repo(monkeypatch, lambda key: None)
        monkeypatch.delenv("ZOTERO_DB_PATH", raising=False)
        assert zotero_paths.resolve_zotero_db_path() == ""

    def test_mcp_config_receives_configured_path(self, monkeypatch, tmp_path):
        from backend.mcp import config as cfg

        entry = tmp_path / "backend" / "mcp" / "servers" / "zotero" / "__main__.py"
        entry.parent.mkdir(parents=True)
        entry.write_text("# entry")
        monkeypatch.setattr(cfg, "_project_root", lambda: tmp_path)
        monkeypatch.setattr(
            zotero_paths,
            "resolve_zotero_db_path",
            lambda: "/synthetic/Zotero/zotero.sqlite",
        )

        builtins = cfg.builtin_server_configs()
        zotero = next(b for b in builtins if b.name == cfg.BUILTIN_ZOTERO)
        assert zotero.env == {
            "ZOTERO_DB_PATH": "/synthetic/Zotero/zotero.sqlite",
        }


# ---------------------------------------------------------------------------
# prompt 注入门
# ---------------------------------------------------------------------------


class _Registry:
    def __init__(self, names):
        self._names = names

    def list_names(self):
        return list(self._names)


class TestPromptGate:
    def test_prefix_constant(self):
        assert zotero_prompt.ZOTERO_TOOL_PREFIX == "mcp__zotero__"

    def test_gate_true_when_zotero_registered(self):
        registry = _Registry(["read_file", "mcp__zotero__zotero_search"])
        assert zotero_prompt.registry_has_zotero_tool(registry) is True

    def test_gate_false_for_other_servers(self):
        registry = _Registry(["mcp__drawio__render_diagram"])
        assert zotero_prompt.registry_has_zotero_tool(registry) is False

    def test_gate_never_raises(self):
        class _Broken:
            def list_names(self):
                raise RuntimeError("registry broken")

        assert zotero_prompt.registry_has_zotero_tool(_Broken()) is False

    def test_prompt_covers_core_tools(self):
        prompt = zotero_prompt.ZOTERO_TOOL_PROMPT
        for tool in (
            "mcp__zotero__zotero_search",
            "mcp__zotero__zotero_get_item",
            "mcp__zotero__zotero_get_annotations",
            "mcp__zotero__zotero_read_pdf",
            "mcp__zotero__zotero_get_bibtex",
            "mcp__zotero__zotero_related",
            "mcp__zotero__zotero_sync",
        ):
            assert tool in prompt
