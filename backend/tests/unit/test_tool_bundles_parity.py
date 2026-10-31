# ruff: noqa: UP006, UP007, UP035
"""R81：bundle-only 工具装配的黄金快照与 preset 选择证据。

R80 曾用 legacy/bundle 双跑对照证明两条装配路径等价；R81 删除 legacy
后，本文件把当时实测得到的 ONLINE 94 个工具名及顺序钉成黄金快照。
无 ``harness.yaml`` 时必须逐项命中这份清单——这是「删配置即回默认」
的兼容承诺。预设只能从这份全量清单中按原顺序删减，不能重排。
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple
from unittest.mock import patch

import pytest

from backend.application.kernel.harness_config import (
    PRESETS,
    HarnessConfig,
    clear_harness_cache,
)
from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.tool_policy import ToolPolicy
from backend.tools import register_all_tools
from backend.tools.registry import ToolRegistry

_EXPECTED_ONLINE = [
    "bash",
    "bash_output",
    "kill_shell",
    "read_file",
    "write_file",
    "list_dir",
    "web_search",
    "web_fetch",
    "http_download",
    "download_status",
    "download_cancel",
    "memory_search",
    "session_search",
    "execute_code",
    "memory_save",
    "office_list",
    "office_read",
    "office_create",
    "office_update",
    "office_delete",
    "office_restore",
    "office_archive",
    "office_read_pdf",
    "office_generate_pdf",
    "office_read_pdf_form",
    "office_fill_pdf_form",
    "office_analyze_word_template",
    "office_fill_word_template",
    "office_analyze_ppt_template",
    "office_fill_ppt_template",
    "office_analyze",
    "office_journal_parse_template",
    "office_journal_fill_from_content",
    "office_journal_generate_article",
    "office_journal_validate",
    "office_parse_bibtex",
    "office_lint_word",
    "office_read_latex",
    "office_analyze_latex_template",
    "office_fill_latex_template",
    "office_audit_latex",
    "office_audit_latex_pdf",
    "office_compile_latex",
    "office_latexdiff",
    "office_extract_latex_project",
    "office_repair_word",
    "office_refresh_toc",
    "edit_file",
    "glob_search",
    "grep_search",
    "codebase_search",
    "todo_write",
    "structured_output",
    "repl",
    "runtime_probe",
    "project_diagnose",
    "runtime_exec",
    "skill",
    "ask_user_question",
    "agent",
    "file_summary",
    "git_branch",
    "git_checkout",
    "git_stash",
    "git_status",
    "git_diff",
    "git_log",
    "git_commit_message",
    "git_commit",
    "checkpoint_create",
    "checkpoint_list",
    "checkpoint_restore",
    "apply_patch",
    "symbol_search",
    "browser_launch",
    "browser_navigate",
    "browser_snapshot",
    "browser_interact",
    "browser_screenshot",
    "browser_cookies",
    "browser_downloads",
    "browser_close",
    "browser_login",
    "skill_save",
    "text_to_speech",
    "speech_to_text",
    "generate_image",
    "ocr_image",
    "read_sage_config",
    "update_sage_config",
    "diagnose_sage_config",
    "schedule_task",
    "list_scheduled_tasks",
    "cancel_scheduled_task",
    "add_todo",
    "list_todos",
    "complete_todo",
    "update_todo",
    "delete_todo",
    "design_list_systems",
    "design_list_templates",
    "design_generate",
    "design_iterate",
    "design_export",
]


_EXPECTED_SCHEMA_NAMES = [
    "bash",
    "bash_output",
    "kill_shell",
    "read_file",
    "write_file",
    "list_dir",
    "web_search",
    "web_fetch",
    "http_download",
    "download_status",
    "download_cancel",
    "memory_search",
    "session_search",
    "execute_code",
    "memory_save",
    "office_create",
    "office_update",
    "office_delete",
    "office_generate_pdf",
    "office_fill_pdf_form",
    "office_fill_word_template",
    "office_fill_ppt_template",
    "office_parse_bibtex",
    "office_fill_latex_template",
    "edit_file",
    "glob_search",
    "grep_search",
    "codebase_search",
    "todo_write",
    "structured_output",
    "repl",
    "runtime_probe",
    "project_diagnose",
    "runtime_exec",
    "skill",
    "ask_user_question",
    "agent",
    "file_summary",
    "git_branch",
    "git_checkout",
    "git_stash",
    "git_status",
    "git_diff",
    "git_log",
    "git_commit_message",
    "git_commit",
    "checkpoint_create",
    "checkpoint_list",
    "checkpoint_restore",
    "apply_patch",
    "symbol_search",
    "browser_launch",
    "browser_navigate",
    "browser_snapshot",
    "browser_interact",
    "browser_screenshot",
    "browser_cookies",
    "browser_downloads",
    "browser_close",
    "browser_login",
    "skill_save",
    "text_to_speech",
    "speech_to_text",
    "generate_image",
    "read_sage_config",
    "update_sage_config",
    "diagnose_sage_config",
    "schedule_task",
    "list_scheduled_tasks",
    "cancel_scheduled_task",
    "add_todo",
    "list_todos",
    "complete_todo",
    "update_todo",
    "delete_todo",
    "design_list_systems",
    "design_list_templates",
    "design_generate",
    "design_iterate",
    "design_export",
]
_EXPECTED_BUNDLE_NAMES = (
    "shell",
    "file",
    "web_search",
    "web_fetch",
    "memory",
    "code_exec",
    "memory_write",
    "office_core",
    "office_pdf",
    "office_template",
    "office_analysis",
    "office_journal",
    "office_quality",
    "edit_search",
    "agent_surface",
    "runtime",
    "skill",
    "ask_user",
    "subagent",
    "file_summary",
    "git",
    "checkpoint",
    "symbol_search",
    "browser",
    "skill_save",
    "multimodal",
    "sage_config",
    "schedule",
    "mcp",
    "plugins",
    "todo",
    "design",
)

_FOCUS_BUNDLES = (
    "shell",
    "file",
    "web_search",
    "web_fetch",
    "memory",
    "code_exec",
    "memory_write",
    "edit_search",
    "agent_surface",
    "runtime",
    "skill",
    "ask_user",
    "subagent",
    "file_summary",
    "git",
    "checkpoint",
    "symbol_search",
    "skill_save",
    "sage_config",
    "schedule",
    "mcp",
    "plugins",
    "todo",
)


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
    """出网工具构造时会建 SSL 上下文；Windows 上每次约 2s。

    本文件只比对注册结果、不联网，共享一个不加载系统证书库的上下文，
    把一次全量装配从约 18.5s 降到约 0.3s。
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with patch("ssl.create_default_context", lambda *args, **kwargs: ctx):
        yield


@pytest.fixture(autouse=True)
def _stub_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 注册对黄金快照无贡献却可能访问外部状态，单测里打成 no-op。"""
    import backend.mcp as mcp_pkg

    monkeypatch.setattr(mcp_pkg, "register_mcp_tools", lambda registry: None, raising=False)


@pytest.fixture(autouse=True)
def _stub_plugin_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """R90 动态插件工具不属于静态黄金快照，单测里打成 no-op。"""
    import backend.plugins.tool_bridge as bridge

    monkeypatch.setattr(bridge, "register_plugin_tools", lambda registry: 0)


@pytest.fixture(autouse=True)
def _isolate_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """把用户/项目 harness 路径隔离到本用例的 tmp 目录。"""
    monkeypatch.setenv("SAGE_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAGE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.delenv("SAGE_HARNESS_PRESET", raising=False)
    clear_harness_cache()
    yield
    clear_harness_cache()


def _harness(preset: str, **overrides: bool) -> HarnessConfig:
    return HarnessConfig(
        preset=preset,
        bundle_overrides=dict(overrides),
        flags=PRESETS[preset].flag_values,
    )


def _install_via_facade(mode: NetworkMode = NetworkMode.ONLINE) -> ToolRegistry:
    registry = ToolRegistry()
    register_all_tools(registry, network_policy=NetworkPolicy(mode=mode))
    return registry


def _install_bundles(
    harness: Optional[HarnessConfig] = None,
    mode: NetworkMode = NetworkMode.ONLINE,
) -> ToolRegistry:
    from backend.tools.tool_bundles import install_default_bundles

    registry = ToolRegistry()
    install_default_bundles(
        registry,
        ToolPolicy(),
        NetworkPolicy(mode=mode),
        harness=harness,
    )
    return registry


def _assert_subsequence(names: List[str]) -> None:
    assert [name for name in _EXPECTED_ONLINE if name in set(names)] == names


# ===== 默认 standard：无配置文件时必须与黄金快照逐项一致 =====


def test_standard_online_matches_golden_snapshot() -> None:
    registry = _install_via_facade()

    assert registry.list_names() == _EXPECTED_ONLINE
    assert len(registry.list_names()) == len(set(registry.list_names())) == 104


def test_standard_risks_and_schemas_align_with_golden_snapshot() -> None:
    registry = _install_via_facade()

    assert list(registry.declared_risks()) == _EXPECTED_ONLINE
    assert [schema["name"] for schema in registry.get_schemas_for_llm()] == _EXPECTED_SCHEMA_NAMES


def test_bundle_install_is_deterministic() -> None:
    first = _install_bundles()
    second = _install_bundles()

    assert first.list_names() == second.list_names() == _EXPECTED_ONLINE
    assert first.declared_risks() == second.declared_risks()
    assert first.get_schemas_for_llm() == second.get_schemas_for_llm()


def test_network_gating_counts_and_differences() -> None:
    online = _install_via_facade(NetworkMode.ONLINE).list_names()
    intranet = _install_via_facade(NetworkMode.INTRANET).list_names()
    offline = _install_via_facade(NetworkMode.OFFLINE).list_names()

    assert (len(online), len(intranet), len(offline)) == (104, 103, 99)
    assert set(online) - set(intranet) == {"web_search"}
    assert set(intranet) - set(offline) == {
        "web_fetch",
        "http_download",
        "download_status",
        "download_cancel",
    }
    _assert_subsequence(intranet)
    _assert_subsequence(offline)


def test_bundle_declarations_cover_the_golden_snapshot() -> None:
    """全量 BUNDLES 不漏不重，且 InstallReport 反映真实差集。"""
    from backend.application.kernel.tool_install import ToolInstallContext, install_bundles
    from backend.tools.tool_bundles import BUNDLES, bundle_names

    assert bundle_names() == _EXPECTED_BUNDLE_NAMES
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

    assert recorder.list_names() == _EXPECTED_ONLINE
    assert list(report.installed) == _EXPECTED_ONLINE
    assert report.failed == ()
    assert report.skipped == ()


# ===== 四预设：只删减，不重排 =====


def test_bundle_selection_for_standard_focus_headless_and_dev() -> None:
    from backend.tools.tool_bundles import BUNDLES, select_bundle_objects

    assert select_bundle_objects(None) == BUNDLES
    assert select_bundle_objects(_harness("standard")) == BUNDLES
    assert select_bundle_objects(_harness("dev")) == BUNDLES
    assert tuple(b.name for b in select_bundle_objects(_harness("focus"))) == _FOCUS_BUNDLES

    headless = tuple(b.name for b in select_bundle_objects(_harness("headless")))
    assert len(headless) == 31
    assert "ask_user" not in headless
    assert [name for name in _EXPECTED_BUNDLE_NAMES if name in set(headless)] == list(headless)


def test_bundle_selection_overrides_preset() -> None:
    from backend.tools.tool_bundles import select_bundle_objects

    config = _harness("focus", office_core=True, shell=False)
    selected = tuple(bundle.name for bundle in select_bundle_objects(config))

    assert "office_core" in selected
    assert "shell" not in selected
    assert [name for name in _EXPECTED_BUNDLE_NAMES if name in set(selected)] == list(selected)


def test_focus_install_excludes_heavy_tool_surfaces() -> None:
    registry = _install_bundles(_harness("focus"))
    names = registry.list_names()

    assert len(names) == 54
    assert not any(name.startswith("office_") for name in names)
    assert not any(name.startswith("browser_") for name in names)
    assert not any(name.startswith("design_") for name in names)
    assert not {"text_to_speech", "speech_to_text", "generate_image", "ocr_image"} & set(names)
    assert {"bash", "read_file", "ask_user_question", "agent"} <= set(names)
    _assert_subsequence(names)


def test_headless_install_excludes_ask_user_only() -> None:
    registry = _install_bundles(_harness("headless"))
    names = registry.list_names()

    assert len(names) == 103
    assert "ask_user_question" not in names
    assert set(_EXPECTED_ONLINE) - set(names) == {"ask_user_question"}
    _assert_subsequence(names)


def test_focus_install_report_matches_registry() -> None:
    from backend.tools.tool_bundles import install_default_bundles

    registry = ToolRegistry()
    report = install_default_bundles(
        registry,
        ToolPolicy(),
        NetworkPolicy(mode=NetworkMode.ONLINE),
        harness=_harness("focus"),
    )

    assert report.ok
    assert list(report.installed) == registry.list_names()
    assert report.skipped == ()


# ===== register_all_tools 的文件接线与 fail-open =====


def _write_project_harness(tmp_path: Path, text: str) -> None:
    path = tmp_path / "workspace" / ".sage" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    clear_harness_cache()


def test_register_all_tools_reads_project_harness(tmp_path: Path) -> None:
    _write_project_harness(tmp_path, "preset: headless\n")

    registry = _install_via_facade()

    assert len(registry.list_names()) == 103
    assert "ask_user_question" not in registry.list_names()


def test_register_all_tools_fails_open_to_standard_on_bad_harness(
    tmp_path: Path,
) -> None:
    _write_project_harness(tmp_path, "preset: [not-a-preset\n")

    registry = _install_via_facade()

    assert registry.list_names() == _EXPECTED_ONLINE


# ===== 透传与自引用（从 R80 对照保留的结构断言） =====


def _forwarded(bundle_name: str) -> Tuple[bool, int]:
    from backend.application.kernel.tool_install import ToolInstallContext, install_bundles
    from backend.tools.tool_bundles import BUNDLES

    def scheduler_getter() -> None:
        return None

    def todo_getter() -> None:
        return None

    recorder = _RecordingRegistry()
    bundle = next(item for item in BUNDLES if item.name == bundle_name)
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


def test_execute_code_shares_registry() -> None:
    """``execute_code`` 的 registry 自引用必须仍是同一对象。"""
    registry = _install_bundles()
    name = next(item for item in registry.list_names() if "execute" in item)
    tool = registry.get(name)

    assert tool is not None
    assert _has_attr_value(tool, registry)
