# ruff: noqa: UP006, UP007, UP017, UP035, UP038
"""把 Sage 的 8 个行为面渲染为 fileized harness 文件集（R84）。

组合层职责：kernel 的 ``harness_files`` 只懂 lock/snapshot 机制，不认识
prompt、tools、skills；本模块从既有单一来源收集素材，生成
``HarnessFileSpec`` 列表交给机制层落盘。

除 ``plugins.yaml`` 的 ``harness_config`` 段会成为 R81 的新配置层外，
其余文件在 R84 都是只读投影。导出不读取 settings 密钥、会话、记忆正文
或 skill 附带脚本。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from backend.agents.agents_files import parse_agent_file, sanitize_agent_id
from backend.agents.profiles import create_default_agents
from backend.application.kernel.harness_config import (
    load_harness_config,
    project_harness_path,
    resolved_view,
    user_harness_path,
)
from backend.application.kernel.harness_files import (
    MAX_HARNESS_FILE_BYTES,
    HarnessFilesError,
    HarnessFileSpec,
)
from backend.domain.permission import READ_ONLY_MODES, PermissionMode
from backend.domain.risk import (
    EXTERNAL_TOOLS,
    SHELL_TOOLS,
    WRITE_TOOLS,
    RiskClass,
    is_consequential,
)
from backend.domain.tool_names import EXEC_TOOLS, RUNTIME_EXEC_TOOLS, SANDBOX_TOOLS
from backend.domain.tool_policy import ToolPolicy
from backend.hooks.builtin import list_builtins
from backend.hooks.config import (
    DEFAULT_TIMEOUT_SECONDS,
    HOOK_EVENTS,
    HOOK_TYPES,
    MAX_HOOKS,
    MAX_TIMEOUT_SECONDS,
)
from backend.memory.scoring import PROMOTED_SOURCES, RECENCY_HALF_LIFE_DAYS, RRF_NORM_MAX, WEIGHTS

FILE_VERSION = 1
PROJECT_INSTRUCTION_FILES = ("SAGE.md", "CLAUDE.md", "AGENTS.md")
MAX_PROJECT_INSTRUCTION_BYTES = 512 * 1024
_SKILLS_ENV = "SAGE_SKILLS_DIR"
# Dynamic/external bundles are runtime state, not a static harness baseline.
_EXPORT_EXCLUDED_BUNDLES: Dict[str, str] = {"mcp": "external_discovery", "plugins": "dynamic_plugin_runtime"}

__all__ = [
    "FILE_VERSION",
    "collect_harness_file_specs",
]


def _format_time(value: Optional[Any]) -> str:
    if value is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(value, str):
        return value
    elif isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    else:
        raise HarnessFilesError("harness updated_at must be a datetime or ISO string")
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(value: Any) -> Any:  # noqa: PLR0911 — 递归类型分派
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    return str(value)


def _meta(component: str, provenance: str, owner: str, authority: str, updated_at: str) -> Dict[str, Any]:
    return {
        "version": FILE_VERSION, "component": component, "provenance": provenance,
        "owner": owner, "authority": authority, "updated_at": updated_at,
    }


def _yaml_spec(
    path: str,
    payload: Mapping[str, Any],
    *,
    component: str,
    provenance: str,
    owner: str,
    authority: str,
    updated_at: str,
) -> HarnessFileSpec:
    body: Dict[str, Any] = {"_meta": _meta(component, provenance, owner, authority, updated_at)}
    body.update(_jsonable(dict(payload)))
    return HarnessFileSpec(
        path=path,
        content=yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=120),
        component=component,
        provenance=provenance,
        owner=owner,
        authority=authority,
    )


def _markdown_spec(
    path: str,
    body: str,
    *,
    component: str,
    provenance: str,
    owner: str,
    authority: str,
    updated_at: str,
) -> HarnessFileSpec:
    meta = _meta(component, provenance, owner, authority, updated_at)
    frontmatter = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    content = f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n"
    return HarnessFileSpec(
        path=path,
        content=content,
        component=component,
        provenance=provenance,
        owner=owner,
        authority=authority,
    )


def _root_from_config_path(path: Path) -> Path:
    # <root>/.sage/harness.yaml → <root>
    return path.parent.parent


def _resolve_roots(
    workspace: Optional[Any],
    user_home: Optional[Any],
    environ: Mapping[str, str],
) -> Tuple[Path, Path]:
    workspace_root = _root_from_config_path(project_harness_path(workspace, environ=environ))
    home_root = _root_from_config_path(user_harness_path(user_home, environ=environ))
    return workspace_root, home_root


def _redact_roots(value: Any, workspace: Path, user_home: Path) -> Any:
    if isinstance(value, str):
        text = value
        for root, label in ((workspace, "workspace:"), (user_home, "user:")):
            for candidate in (str(root), root.as_posix()):
                if candidate:
                    text = text.replace(candidate, label)
        return text
    if isinstance(value, list):
        return [_redact_roots(item, workspace, user_home) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _redact_roots(item, workspace, user_home)
            for key, item in value.items()
        }
    return value


def _agent_records(
    workspace: Path,
    *,
    include_workspace_overlays: bool,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    records: Dict[str, Dict[str, Any]] = {}
    provenance: Dict[str, str] = {}
    for profile in create_default_agents():
        records[profile.id] = {
            "id": profile.id,
            "name": profile.name,
            "role": profile.role,
            "description": profile.description,
            "system_prompt": profile.system_prompt,
            "tools": list(profile.tools),
            "memory_access": list(profile.memory_access),
            "max_iterations": profile.max_iterations,
            "enabled": profile.enabled,
            "model_config": {
                "model": profile.model_config.model,
                "temperature": profile.model_config.temperature,
                "max_tokens": profile.model_config.max_tokens,
            },
        }
        provenance[profile.id] = f"backend.agents.profiles:create_default_agents#{profile.id}"

    if include_workspace_overlays:
        agents_root = workspace / ".sage" / "agents"
        if agents_root.is_symlink():
            raise HarnessFilesError("workspace agents directory must not be a symlink")
        if agents_root.is_dir():
            for path in sorted(agents_root.glob("*.md")):
                if path.is_symlink() or not path.is_file():
                    raise HarnessFilesError(
                        f"workspace agent file must be a regular file: {path.name}"
                    )
                parsed = parse_agent_file(path)
                agent_id = str(parsed["id"])
                records[agent_id] = parsed
                provenance[agent_id] = f"workspace:.sage/agents/{path.name}"
    return records, provenance


def _frontmatter_value(value: Any) -> str:
    return " ".join(str(value or "").splitlines()).strip()


def _agent_markdown(
    record: Mapping[str, Any],
    *,
    provenance: str,
    owner: str,
    authority: str,
    updated_at: str,
) -> str:
    model = record.get("model_config") or {}
    lines = [
        f"version: {FILE_VERSION}",
        f"provenance: {_frontmatter_value(provenance)}",
        f"owner: {_frontmatter_value(owner)}",
        f"updated_at: {_frontmatter_value(updated_at)}",
        f"name: {_frontmatter_value(record.get('name'))}",
        f"role: {_frontmatter_value(record.get('role'))}",
        f"description: {_frontmatter_value(record.get('description'))}",
        "tools: " + ", ".join(str(item) for item in record.get("tools") or []),
        "memory_access: "
        + ", ".join(str(item) for item in record.get("memory_access") or []),
        f"max_iterations: {int(record.get('max_iterations') or 10)}",
        f"enabled: {'true' if bool(record.get('enabled', True)) else 'false'}",
        f"model: {_frontmatter_value(model.get('model', 'gpt-3.5-turbo'))}",
        f"temperature: {float(model.get('temperature', 0.7))}",
        f"max_tokens: {int(model.get('max_tokens', 4096))}",
        f"authority: {_frontmatter_value(authority)}",
    ]
    body = str(record.get("system_prompt") or "").rstrip()
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body + "\n"


def _project_instruction_sections(workspace: Path) -> Tuple[str, List[str]]:
    sections: List[str] = []
    sources: List[str] = []
    for name in PROJECT_INSTRUCTION_FILES:
        path = workspace / name
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise HarnessFilesError(f"project instruction is not a regular file: {name}")
        data = path.read_bytes()
        sources.append(f"workspace:{name}")
        sections.append(f"## Project instructions: {name}")
        if len(data) > MAX_PROJECT_INSTRUCTION_BYTES:
            sections.append(
                "Content omitted from the harness projection because it exceeds "
                f"{MAX_PROJECT_INSTRUCTION_BYTES} bytes "
                f"(size={len(data)}, sha256={hashlib.sha256(data).hexdigest()})."
            )
            continue
        try:
            sections.append(data.decode("utf-8").rstrip())
        except UnicodeDecodeError:
            sections.append(
                "Content omitted from the harness projection because it is not "
                f"valid UTF-8 (size={len(data)}, "
                f"sha256={hashlib.sha256(data).hexdigest()})."
            )
    if not sections:
        return "", sources
    return "\n\n" + "\n\n".join(sections) + "\n", sources


def _memory_payload() -> Dict[str, Any]:
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    configured: Dict[str, Any] = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, Mapping) and isinstance(loaded.get("memory"), Mapping):
            configured = dict(loaded["memory"])
    return {
        "configured": configured,
        "scoring": {
            "weights": dict(WEIGHTS),
            "recency_half_life_days": RECENCY_HALF_LIFE_DAYS,
            "rrf_norm_max": RRF_NORM_MAX,
            "promoted_sources": sorted(PROMOTED_SOURCES),
        },
        "classification": {
            "semantic_importance_min": 8,
            "working_max_chars_exclusive": 200,
            "working_importance_max_exclusive": 5,
            "default": "episodic",
        },
        "content_exported": False,
    }


def _load_effective_config(
    *,
    scope: str,
    workspace: Path,
    user_home: Path,
    environ: Mapping[str, str],
    known_bundles: Sequence[str],
):
    config_workspace: Path = workspace
    if scope == "user":
        # user 文件集只钉 user 层 + builtin/env，不把当前项目选择烘焙进去。
        config_workspace = user_home / ".sage" / ".harness-export-no-workspace"
    return load_harness_config(
        workspace=config_workspace,
        user_home=user_home,
        environ=environ,
        known_bundles=known_bundles,
    )


def _tool_guidance_payload(
    config: Any,
    *,
    workspace: Path,
    include_tool_schemas: bool,
) -> Dict[str, Any]:
    from backend.application.kernel.tool_install import install_bundles
    from backend.domain.network_policy import NetworkMode, NetworkPolicy
    from backend.tools.registry import ToolRegistry
    from backend.tools.tool_bundles import BUNDLES, build_context, select_bundle_objects

    selected_bundles = select_bundle_objects(config)
    exported_bundles = tuple(
        bundle for bundle in selected_bundles if bundle.name not in _EXPORT_EXCLUDED_BUNDLES
    )
    bundle_rows: List[Dict[str, Any]] = []
    tools: List[Dict[str, Any]] = []

    if include_tool_schemas:
        registry = ToolRegistry()
        context = build_context(
            registry,
            ToolPolicy(workspace_root=str(workspace)),
            NetworkPolicy(mode=NetworkMode.ONLINE),
        )
        bundle_by_tool: Dict[str, str] = {}
        tools_by_bundle: Dict[str, List[str]] = {}
        for bundle in exported_bundles:
            report = install_bundles(context, (bundle,), strict=True)
            names = list(report.installed)
            tools_by_bundle[bundle.name] = names
            for name in names:
                bundle_by_tool[name] = bundle.name
        declared = registry.declared_risks()
        for schema in registry.list():
            tool = registry.get(schema.name)
            risk = declared.get(schema.name, RiskClass.READ)
            tools.append(
                {
                    "name": schema.name,
                    "description": schema.description,
                    "bundle": bundle_by_tool.get(schema.name, ""),
                    "risk": risk.value,
                    "requires_tool_context": bool(
                        getattr(tool, "requires_tool_context", False)
                    ),
                    "parameters": _jsonable(schema.parameters),
                }
            )
    else:
        tools_by_bundle = {bundle.name: [] for bundle in exported_bundles}

    selected_names = {bundle.name for bundle in selected_bundles}
    for bundle in BUNDLES:
        if bundle.name in _EXPORT_EXCLUDED_BUNDLES:
            status, reason = "excluded_from_export", _EXPORT_EXCLUDED_BUNDLES[bundle.name]
        elif bundle.name in selected_names:
            status = "selected"
            reason = ""
        else:
            status = "skipped"
            reason = config.skipped_reason(bundle.name) or "preset"
        bundle_rows.append(
            {
                "name": bundle.name,
                "status": status,
                "reason": reason,
                "requires": list(bundle.requires),
                "critical": bool(bundle.critical),
                "tools": tools_by_bundle.get(bundle.name, []),
            }
        )

    return {
        "network_mode_for_export": NetworkMode.ONLINE.value,
        "schemas_included": bool(include_tool_schemas),
        "excluded_bundles": [
            {"name": name, "reason": reason} for name, reason in _EXPORT_EXCLUDED_BUNDLES.items()],
        "bundles": bundle_rows,
        "tools": tools,
    }


def _plugins_payload(
    config: Any,
    *,
    known_bundles: Sequence[str],
    workspace: Path,
    user_home: Path,
) -> Dict[str, Any]:
    preset_defaults = dict(config.preset_definition.flag_values)
    flag_overrides = {
        key: value
        for key, value in config.flags.items()
        if preset_defaults.get(key) != value
    }
    resolved = _redact_roots(
        resolved_view(config, known_bundles), workspace, user_home
    )
    return {
        "harness_config": {
            "preset": config.preset,
            "bundles": dict(config.bundle_overrides),
            "flags": flag_overrides,
        },
        "resolved": resolved,
        "hooks": {
            "events": list(HOOK_EVENTS),
            "types": list(HOOK_TYPES),
            "limits": {
                "max_hooks": MAX_HOOKS,
                "default_timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
                "max_timeout_seconds": MAX_TIMEOUT_SECONDS,
            },
            "builtins": _jsonable(list_builtins()),
        },
        "runtime": {
            "plugin_host": "subprocess",
            "notes": [
                "Only harness_config is a runtime input in R84.",
                "Hook entries are a projection of builtin metadata and limits.",
            ],
        },
    }


def _skill_specs(
    *,
    scope: str,
    workspace: Path,
    user_home: Path,
    environ: Mapping[str, str],
) -> List[HarnessFileSpec]:
    backend_dir = Path(__file__).resolve().parent.parent
    shipped = backend_dir / "skills" / "skill_md" / "shipped"
    roots: List[Tuple[Path, str, str]] = [
        (shipped, "shipped", "sage-builtin"),
        (user_home / ".sage" / "skills", "user", "user"),
    ]
    if scope == "project":
        roots.append((workspace / "skills", "workspace", "workspace"))
    env_root = str(environ.get(_SKILLS_ENV, "") or "").strip()
    if env_root:
        roots.append((Path(env_root).expanduser(), "env", "user"))

    selected: Dict[str, HarnessFileSpec] = {}
    for root, label, owner in roots:
        if root.is_symlink() or not root.is_dir():
            continue
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if skill_file.is_symlink() or not skill_file.is_file():
                continue
            data = skill_file.read_bytes()
            if len(data) > MAX_HARNESS_FILE_BYTES:
                raise HarnessFilesError(
                    f"skill file exceeds harness size limit: {child.name}/SKILL.md"
                )
            relative = f"skills/{child.name}/SKILL.md"
            if label == "shipped":
                provenance = f"shipped:skills/{child.name}/SKILL.md"
            elif label == "env":
                provenance = f"env:{_SKILLS_ENV}/{child.name}/SKILL.md"
            elif label == "workspace":
                provenance = f"workspace:skills/{child.name}/SKILL.md"
            else:
                provenance = f"user:.sage/skills/{child.name}/SKILL.md"
            selected[relative] = HarnessFileSpec(
                path=relative,
                content=data,
                component="skills",
                provenance=provenance,
                owner=owner,
                authority="existing-file",
            )
    return [selected[path] for path in sorted(selected)]


def collect_harness_file_specs(
    *,
    workspace: Optional[Any] = None,
    user_home: Optional[Any] = None,
    environ: Optional[Mapping[str, str]] = None,
    scope: str = "project",
    updated_at: Optional[Any] = None,
    include_tool_schemas: bool = True,
) -> List[HarnessFileSpec]:
    """收集 8 个行为面的当前投影，返回待落盘 specs。"""
    if scope not in ("project", "user"):
        raise HarnessFilesError(f"invalid harness export scope: {scope!r}")
    env: Mapping[str, str] = os.environ if environ is None else environ
    workspace_path, home_path = _resolve_roots(workspace, user_home, env)
    timestamp = _format_time(updated_at)
    include_workspace = scope == "project"
    scope_owner = "workspace" if scope == "project" else "user"

    from backend.tools.tool_bundles import bundle_names

    known_bundles = bundle_names()
    config = _load_effective_config(
        scope=scope,
        workspace=workspace_path,
        user_home=home_path,
        environ=env,
        known_bundles=known_bundles,
    )

    specs: List[HarnessFileSpec] = [
        HarnessFileSpec(
            path=".gitignore",
            content="# Harness snapshots are local rollback state.\n.snapshots/\n",
            component="meta",
            provenance="backend.cli.harness_export:static",
            owner="sage-builtin",
            authority="projection",
        )
    ]

    agents, agent_provenance = _agent_records(
        workspace_path, include_workspace_overlays=include_workspace
    )
    primary = agents.get("primary")
    if primary is None:
        raise HarnessFilesError("primary agent profile is missing")
    system_body = str(primary.get("system_prompt") or "").rstrip()
    system_sources = [agent_provenance["primary"]]
    if include_workspace:
        instruction_text, instruction_sources = _project_instruction_sections(
            workspace_path
        )
        system_body += instruction_text
        system_sources.extend(instruction_sources)
    system_owner = (
        "workspace"
        if any(source.startswith("workspace:") for source in system_sources)
        else "sage-builtin"
    )
    specs.append(
        _markdown_spec(
            "system.md",
            system_body,
            component="system",
            provenance="; ".join(system_sources),
            owner=system_owner,
            authority="projection",
            updated_at=timestamp,
        )
    )

    policy = ToolPolicy()
    specs.append(
        _yaml_spec(
            "guardrails.yaml",
            {
                "tool_policy": {
                    "timeout_seconds": policy.timeout_seconds,
                    "max_output_bytes": policy.max_output_bytes,
                    "max_result_items": policy.max_result_items,
                    "max_read_bytes": policy.max_read_bytes,
                    "max_tool_calls_per_run": policy.max_tool_calls_per_run,
                    "workspace_root": "workspace:",
                    "subagent_only_default": policy.subagent_only,
                },
                "permissions": {
                    "default_mode": PermissionMode.INTERACTIVE.value,
                    "modes": [mode.value for mode in PermissionMode],
                    "read_only_modes": sorted(mode.value for mode in READ_ONLY_MODES),
                },
                "risks": {
                    "classes": [
                        {
                            "name": risk.value,
                            "consequential": is_consequential(risk),
                        }
                        for risk in RiskClass
                    ],
                    "name_fallbacks": {
                        "write_local": sorted(WRITE_TOOLS),
                        "exec": sorted(SHELL_TOOLS),
                        "external": sorted(EXTERNAL_TOOLS),
                    },
                },
                "hooks": {
                    "events": list(HOOK_EVENTS),
                    "types": list(HOOK_TYPES),
                    "limits": {
                        "max_hooks": MAX_HOOKS,
                        "default_timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
                        "max_timeout_seconds": MAX_TIMEOUT_SECONDS,
                    },
                    "builtin_guards": [
                        item["id"]
                        for item in list_builtins()
                        if str(item.get("id", "")).endswith("_guard")
                    ],
                },
            },
            component="guardrails",
            provenance="backend.domain.tool_policy; backend.domain.permission; backend.domain.risk; backend.hooks.config",
            owner="sage-builtin",
            authority="projection",
            updated_at=timestamp,
        )
    )

    specs.append(
        _yaml_spec(
            "memory.yaml",
            _memory_payload(),
            component="memory",
            provenance="backend/config.yaml#memory; backend.memory.scoring; backend.memory.manager:classify_memory_type",
            owner="sage-builtin",
            authority="projection",
            updated_at=timestamp,
        )
    )

    specs.append(
        _yaml_spec(
            "plugins.yaml",
            _plugins_payload(
                config,
                known_bundles=known_bundles,
                workspace=workspace_path,
                user_home=home_path,
            ),
            component="plugins",
            provenance="backend.application.kernel.harness_config; backend.hooks.builtin; backend.hooks.config",
            owner=scope_owner,
            authority="configuration",
            updated_at=timestamp,
        )
    )

    specs.append(
        _yaml_spec(
            "tool-guidance.yaml",
            _tool_guidance_payload(
                config,
                workspace=workspace_path,
                include_tool_schemas=include_tool_schemas,
            ),
            component="tool-guidance",
            provenance="backend.tools.tool_bundles; backend.tools.registry",
            owner="sage-builtin",
            authority="projection",
            updated_at=timestamp,
        )
    )

    seen_agent_files: Dict[str, str] = {}
    for agent_id in sorted(agents):
        file_id = sanitize_agent_id(agent_id)
        relative = f"subagents/{file_id}.md"
        if relative in seen_agent_files:
            raise HarnessFilesError(
                f"agent ids collide after sanitization: {agent_id!r}"
            )
        seen_agent_files[relative] = agent_id
        provenance = agent_provenance[agent_id]
        owner = "workspace" if provenance.startswith("workspace:") else "sage-builtin"
        authority = "existing-file" if owner == "workspace" else "projection"
        specs.append(
            HarnessFileSpec(
                path=relative,
                content=_agent_markdown(
                    agents[agent_id],
                    provenance=provenance,
                    owner=owner,
                    authority=authority,
                    updated_at=timestamp,
                ),
                component="subagents",
                provenance=provenance,
                owner=owner,
                authority=authority,
            )
        )

    specs.extend(
        _skill_specs(
            scope=scope,
            workspace=workspace_path,
            user_home=home_path,
            environ=env,
        )
    )

    specs.append(
        _yaml_spec(
            "scripts/policy.yaml",
            {
                "execution_tools": {
                    "shell": list(EXEC_TOOLS),
                    "sandbox": list(SANDBOX_TOOLS),
                    "runtime_exec": list(RUNTIME_EXEC_TOOLS),
                },
                "command_allowlist": [],
                "allowlist_semantics": {
                    "match": "exact token prefix",
                    "shell_metacharacters": "never auto-allowed",
                    "source": "PermissionEngine allowed_commands (default empty in R84 projection)",
                },
                "skill_script_roots": [
                    "env:SAGE_SKILLS_DIR",
                    "workspace:skills",
                    "user:.sage/skills",
                ],
                "scripts_copied": False,
            },
            component="scripts",
            provenance="backend.domain.tool_names; backend.services.permission_gate",
            owner="sage-builtin",
            authority="projection",
            updated_at=timestamp,
        )
    )
    static_docs = (
        (
            "scripts/README.md",
            "scripts",
            "# Scripts policy\n\n`policy.yaml` is a read-only projection of the "
            "execution tool surface. R84 does not copy executable scripts into "
            "the harness file set; skill scripts remain behind the existing "
            "sandbox and approval boundaries.",
        ),
        (
            "proposals/README.md",
            "proposals",
            "# Proposals\n\nR85 stores one directory per harness proposal. Each "
            "manifest is anchored to a harness lock and must cite trajectory "
            "evidence. Only this README is lock-managed; proposal artifacts are "
            "validated by the proposal engine and change managed files only "
            "after human approval.",
        ),
        (
            "evidence/README.md",
            "evidence",
            "# Evidence\n\nR85 evidence records are content-hashed JSON excerpts "
            "from sessions, messages, tool trajectories, or LLM replays. Only "
            "this README is lock-managed; evidence files are validated when "
            "referenced by a proposal.",
        ),
    )
    for path, component, body in static_docs:
        specs.append(
            _markdown_spec(
                path,
                body,
                component=component,
                provenance="backend.cli.harness_export:static",
                owner="sage-builtin",
                authority="projection",
                updated_at=timestamp,
            )
        )

    return sorted(specs, key=lambda item: item.normalized_path)
