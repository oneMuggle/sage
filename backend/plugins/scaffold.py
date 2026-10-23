# ruff: noqa: UP006, UP007, UP035
"""Plugin package scaffolding, validation, and dev smoke (R86).

Package validation is static: it parses manifests and Python ASTs but never
imports plugin code.  Code is executed only by :func:`run_plugin_dev`, which
reuses the R82 lifecycle store in a temporary database and the R83
out-of-process host.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.plugins.manifest import CapabilityType, PluginCapability, PluginManifest
from backend.plugins.scaffold_templates import (
    _PERMISSION_RE,
    TEMPLATE_NAMES,
    PluginEcosystemError,
    ScaffoldOptions,
    ScaffoldResult,
    _manifest_for_template,
    _render_files,
    list_templates,
)

_KNOWN_PERMISSION_SCOPES = {
    "clipboard",
    "database",
    "env",
    "file",
    "network",
    "notification",
    "process",
}
_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
_CONVENTIONAL_ATTRS = ("run", "execute", "handler", "main")


@dataclass(frozen=True)
class PluginValidationIssue:
    """One static plugin-package finding."""

    code: str
    severity: str
    message: str
    path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True)
class PluginPackageValidation:
    """Result of static plugin-package validation."""

    root: Path
    manifest: Optional[PluginManifest]
    issues: Tuple[PluginValidationIssue, ...] = field(default_factory=tuple)
    strict: bool = False

    @property
    def errors(self) -> Tuple[PluginValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> Tuple[PluginValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        if self.errors:
            return False
        return not (self.strict and self.warnings)

    @property
    def permissions(self) -> List[str]:
        if self.manifest is None:
            return []
        permissions: List[str] = []
        seen = set()
        for capability in self.manifest.capabilities:
            for permission in capability.permissions:
                if permission not in seen:
                    seen.add(permission)
                    permissions.append(permission)
        return permissions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "root": str(self.root),
            "strict": self.strict,
            "plugin": self.manifest.to_dict() if self.manifest is not None else None,
            "permissions": self.permissions,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PluginDevResult:
    """One explicit lifecycle + out-of-process invoke smoke run."""

    root: Path
    manifest: PluginManifest
    capability: str
    arguments: Dict[str, Any]
    result: Any
    runtime: Dict[str, Any]
    record: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "root": str(self.root),
            "plugin": self.manifest.to_dict(),
            "capability": self.capability,
            "arguments": dict(self.arguments),
            "result": self.result,
            "runtime": dict(self.runtime),
            "record": dict(self.record),
        }


def _safe_relative_path(relative: str) -> Path:
    if not relative or "\\" in relative:
        raise PluginEcosystemError(
            "INVALID_SCAFFOLD_PATH",
            f"scaffold path must be a POSIX relative path: {relative!r}",
            status_code=500,
        )
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise PluginEcosystemError(
            "INVALID_SCAFFOLD_PATH",
            f"scaffold path escapes its root: {relative!r}",
            status_code=500,
        )
    return path


def _write_files(root: Path, files: Dict[str, str], *, force: bool) -> None:
    destinations = {relative: root / _safe_relative_path(relative) for relative in files}
    if root.exists() and not root.is_dir():
        raise PluginEcosystemError(
            "PLUGIN_OUTPUT_NOT_DIRECTORY",
            f"plugin output is not a directory: {root}",
            status_code=409,
        )
    overlaps = [relative for relative, path in destinations.items() if path.exists()]
    if overlaps and not force:
        raise PluginEcosystemError(
            "PLUGIN_OUTPUT_EXISTS",
            "refusing to overwrite existing scaffold files: " + ", ".join(sorted(overlaps)),
            status_code=409,
            details={"existing_files": sorted(overlaps)},
        )

    root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{root.name}.sage-stage-", dir=str(root.parent)))
    try:
        for relative, content in files.items():
            target = stage / _safe_relative_path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))

        if not root.exists():
            stage.replace(root)
            return

        for relative in files:
            source = stage / _safe_relative_path(relative)
            destination = destinations[relative]
            if destination.exists() and destination.is_dir():
                raise PluginEcosystemError(
                    "PLUGIN_OUTPUT_CONFLICT",
                    f"scaffold destination is a directory: {relative}",
                    status_code=409,
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source), str(destination))
    except PluginEcosystemError:
        raise
    except OSError as exc:
        raise PluginEcosystemError(
            "PLUGIN_SCAFFOLD_WRITE_FAILED",
            f"could not write plugin scaffold: {exc}",
            status_code=500,
        ) from exc
    finally:
        if stage.exists():
            shutil.rmtree(str(stage), ignore_errors=True)


def scaffold_plugin(options: ScaffoldOptions) -> ScaffoldResult:
    """Render a new plugin package without executing generated code."""

    manifest = _manifest_for_template(options)
    root = options.output_dir.expanduser() if options.output_dir is not None else Path(manifest.name)
    if not root.is_absolute():
        root = Path.cwd() / root
    files = _render_files(options, manifest)
    _write_files(root, files, force=options.force)

    validation = validate_plugin_package(root)
    if validation.errors:
        raise PluginEcosystemError(
            "GENERATED_PLUGIN_INVALID",
            "generated plugin failed its own validation",
            status_code=500,
            details={"validation": validation.to_dict()},
        )
    return ScaffoldResult(
        root=root,
        manifest=manifest,
        template=options.template.strip().lower(),
        files=tuple(sorted(files)),
    )


def _issue(
    code: str,
    severity: str,
    message: str,
    path: Optional[str] = None,
) -> PluginValidationIssue:
    return PluginValidationIssue(code=code, severity=severity, message=message, path=path)


def _capability_type(capability: PluginCapability) -> str:
    return str(getattr(capability.type, "value", capability.type))


def _module_file(root: Path, module_name: str) -> Optional[Path]:
    parts = module_name.split(".")
    module_path = root.joinpath(*parts).with_suffix(".py")
    if module_path.is_file():
        return module_path
    package_path = root.joinpath(*parts) / "__init__.py"
    if package_path.is_file():
        return package_path
    return None


def _top_level_names(tree: ast.AST) -> set:
    names = set()
    body = getattr(tree, "body", [])
    for node in body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):  # noqa: UP038 - py38 tuple form
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):  # noqa: UP038 - py38 tuple form
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _validate_python_entry(
    root: Path,
    entry_point: str,
    issues: List[PluginValidationIssue],
) -> None:
    value = entry_point.strip()
    paths = value.split(":", 1) if ":" in value else [value]
    invalid = (
        not value
        or value.count(":") > 1
        or any(not path or any(not part.isidentifier() for part in path.split(".")) for path in paths)
    )
    if invalid:
        issues.append(
            _issue(
                "INVALID_ENTRY_POINT",
                "error",
                f"invalid Python entry_point: {entry_point!r}",
                "plugin.json",
            )
        )
        return

    attr_path: Optional[str] = None
    module_name = paths[0]
    if len(paths) == 2:
        attr_path = paths[1]
        module_file = _module_file(root, module_name)
    else:
        module_file = _module_file(root, module_name)
        if module_file is None and "." in module_name:
            module_name, attr_path = module_name.rsplit(".", 1)
            module_file = _module_file(root, module_name)

    if module_file is None:
        issues.append(
            _issue(
                "ENTRY_POINT_MODULE_NOT_FOUND",
                "error",
                f"entry_point module was not found below the plugin root: {entry_point!r}",
                "plugin.json",
            )
        )
        return

    try:
        tree = ast.parse(module_file.read_text(encoding="utf-8"), filename=str(module_file))
    except (OSError, SyntaxError, UnicodeError) as exc:
        issues.append(
            _issue(
                "ENTRY_POINT_UNREADABLE",
                "error",
                f"could not parse entry_point module: {exc}",
                str(module_file.relative_to(root)),
            )
        )
        return

    names = _top_level_names(tree)
    if attr_path:
        first_attr = attr_path.split(".")[0]
        if first_attr not in names:
            issues.append(
                _issue(
                    "ENTRY_POINT_ATTR_NOT_STATICALLY_FOUND",
                    "warning",
                    "entry_point attribute was not found statically; it may be "
                    f"created dynamically: {entry_point!r}",
                    str(module_file.relative_to(root)),
                )
            )
    elif not any(name in names for name in _CONVENTIONAL_ATTRS):
        issues.append(
            _issue(
                "ENTRY_POINT_CONVENTION_MISSING",
                "warning",
                "module entry_point defines none of run/execute/handler/main",
                str(module_file.relative_to(root)),
            )
        )


def _path_within(root: Path, raw_path: str) -> Optional[Path]:
    value = raw_path.strip().replace("\\", "/")
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return None
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _validate_skill_entry(
    root: Path,
    capability: PluginCapability,
    issues: List[PluginValidationIssue],
) -> None:
    path = _path_within(root, capability.entry_point or "")
    if path is None:
        issues.append(
            _issue(
                "SKILL_ENTRY_OUTSIDE_ROOT",
                "error",
                f"skill entry_point must be a relative path below the plugin root: {capability.entry_point!r}",
                "plugin.json",
            )
        )
        return
    if not path.is_file():
        issues.append(
            _issue(
                "SKILL_ENTRY_NOT_FOUND",
                "error",
                f"skill entry_point does not exist: {capability.entry_point!r}",
                "plugin.json",
            )
        )
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        issues.append(
            _issue("SKILL_ENTRY_UNREADABLE", "error", str(exc), capability.entry_point)
        )
        return
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        issues.append(
            _issue(
                "SKILL_FRONTMATTER_MISSING",
                "error",
                "SKILL.md must start with YAML frontmatter",
                capability.entry_point,
            )
        )
        return
    frontmatter = text[4:].split("\n---", 1)[0]
    for key in ("name", "description"):
        if not re.search(rf"^{key}:\s*\S+", frontmatter, flags=re.MULTILINE):
            issues.append(
                _issue(
                    "SKILL_FRONTMATTER_FIELD_MISSING",
                    "error",
                    f"SKILL.md frontmatter must define {key}",
                    capability.entry_point,
                )
            )


def _validate_capabilities(
    root: Path,
    manifest: PluginManifest,
    issues: List[PluginValidationIssue],
) -> None:
    if not manifest.capabilities:
        issues.append(
            _issue(
                "NO_CAPABILITIES",
                "error",
                "plugin manifest declares no capabilities",
                "plugin.json",
            )
        )
        return

    for capability in manifest.capabilities:
        capability_type = _capability_type(capability)
        seen_permissions = set()
        for permission in capability.permissions:
            if permission in seen_permissions:
                issues.append(
                    _issue(
                        "DUPLICATE_PERMISSION",
                        "warning",
                        f"capability {capability.name!r} repeats permission {permission!r}",
                        "plugin.json",
                    )
                )
            seen_permissions.add(permission)
            if not _PERMISSION_RE.match(permission):
                issues.append(
                    _issue(
                        "INVALID_PERMISSION",
                        "error",
                        f"permission must use lowercase scope:action form: {permission!r}",
                        "plugin.json",
                    )
                )
            elif permission.split(":", 1)[0] not in _KNOWN_PERMISSION_SCOPES:
                issues.append(
                    _issue(
                        "UNKNOWN_PERMISSION_SCOPE",
                        "warning",
                        f"unknown permission scope in {permission!r}; it will be shown verbatim during install review",
                        "plugin.json",
                    )
                )

        if capability_type == CapabilityType.TOOL.value:
            if not capability.entry_point:
                issues.append(
                    _issue(
                        "TOOL_ENTRY_POINT_MISSING",
                        "error",
                        f"tool capability {capability.name!r} has no entry_point for the R83 host",
                        "plugin.json",
                    )
                )
            else:
                _validate_python_entry(root, capability.entry_point, issues)
            continue

        issues.append(
            _issue(
                "RUNTIME_PREVIEW_ONLY",
                "warning",
                f"{capability_type} capability {capability.name!r} is manifest-supported but not executed by the R83 host",
                "plugin.json",
            )
        )
        if not capability.entry_point:
            issues.append(
                _issue(
                    "CAPABILITY_ENTRY_POINT_MISSING",
                    "warning",
                    f"{capability_type} capability {capability.name!r} has no entry_point",
                    "plugin.json",
                )
            )
        elif capability_type == CapabilityType.SKILL.value:
            _validate_skill_entry(root, capability, issues)
        elif capability_type == CapabilityType.MCP_SERVER.value and (
            capability.entry_point.endswith(".py") or "/" in capability.entry_point
        ):
            path = _path_within(root, capability.entry_point)
            if path is None or not path.is_file():
                issues.append(
                    _issue(
                        "MCP_ENTRY_NOT_FOUND",
                        "error",
                        f"MCP entry_point does not exist below the plugin root: {capability.entry_point!r}",
                        "plugin.json",
                    )
                )
        else:
            _validate_python_entry(root, capability.entry_point, issues)


def _validate_python_syntax(
    root: Path,
    issues: List[PluginValidationIssue],
) -> None:
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in relative.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            issues.append(
                _issue(
                    "PYTHON_SYNTAX_ERROR",
                    "error",
                    f"could not parse Python file: {exc}",
                    str(relative),
                )
            )


def _validate_local_asset(
    root: Path,
    value: Optional[str],
    field_name: str,
    issues: List[PluginValidationIssue],
) -> None:
    if not value or value.startswith(("http://", "https://", "data:")):
        return
    path = _path_within(root, value)
    if path is None or not path.exists():
        issues.append(
            _issue(
                "LOCAL_ASSET_NOT_FOUND",
                "warning",
                f"manifest {field_name} does not exist below the plugin root: {value!r}",
                "plugin.json",
            )
        )


def validate_plugin_package(
    root: Path,
    *,
    strict: bool = False,
) -> PluginPackageValidation:
    """Statically validate a plugin directory without importing its code."""

    root = Path(root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    issues: List[PluginValidationIssue] = []
    manifest: Optional[PluginManifest] = None

    if not root.is_dir():
        issues.append(
            _issue("PLUGIN_ROOT_NOT_FOUND", "error", f"plugin root is not a directory: {root}")
        )
        return PluginPackageValidation(root=root, manifest=None, issues=tuple(issues), strict=strict)

    manifest_path = root / "plugin.json"
    raw: Any = None
    if not manifest_path.is_file():
        issues.append(
            _issue("PLUGIN_MANIFEST_MISSING", "error", "plugin.json is missing", "plugin.json")
        )
    else:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            issues.append(
                _issue("PLUGIN_MANIFEST_INVALID_JSON", "error", str(exc), "plugin.json")
            )
        else:
            if not isinstance(raw, dict):
                issues.append(
                    _issue(
                        "PLUGIN_MANIFEST_NOT_OBJECT",
                        "error",
                        "plugin.json top level must be an object",
                        "plugin.json",
                    )
                )
            else:
                try:
                    manifest = PluginManifest.from_file(manifest_path)
                except (OSError, TypeError, ValueError) as exc:
                    issues.append(
                        _issue("PLUGIN_MANIFEST_INVALID", "error", str(exc), "plugin.json")
                    )

    if manifest is not None and isinstance(raw, dict):
        model_fields = getattr(PluginManifest, "model_fields", None) or getattr(
            PluginManifest, "__fields__", {}
        )
        unknown = sorted(set(raw) - set(model_fields))
        if unknown:
            issues.append(
                _issue(
                    "UNKNOWN_MANIFEST_FIELDS",
                    "warning",
                    "manifest contains fields ignored by the current schema: "
                    + ", ".join(unknown),
                    "plugin.json",
                )
            )
        if root.name.strip().lower() != manifest.name:
            issues.append(
                _issue(
                    "PLUGIN_DIRECTORY_NAME_MISMATCH",
                    "warning",
                    f"plugin directory {root.name!r} differs from manifest name {manifest.name!r}",
                )
            )
        for hook_name in manifest.hooks:
            if not hook_name.isidentifier():
                issues.append(
                    _issue(
                        "INVALID_HOOK_NAME",
                        "warning",
                        f"manifest hook is not a Python identifier: {hook_name!r}",
                        "plugin.json",
                    )
                )
        _validate_local_asset(root, manifest.metadata.icon, "metadata.icon", issues)
        _validate_local_asset(
            root,
            manifest.metadata.hero_image,
            "metadata.hero_image",
            issues,
        )
        _validate_capabilities(root, manifest, issues)

    if not (root / "README.md").is_file():
        issues.append(
            _issue(
                "PLUGIN_README_MISSING",
                "warning",
                "plugin package has no README.md",
                "README.md",
            )
        )
    _validate_python_syntax(root, issues)
    return PluginPackageValidation(
        root=root,
        manifest=manifest,
        issues=tuple(issues),
        strict=strict,
    )


def _model_to_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def run_plugin_dev(
    root: Path,
    *,
    capability_name: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> PluginDevResult:
    """Run one explicit R83 tool invoke against a local plugin package.

    This is intentionally one-shot rather than a watch server. It uses a
    temporary lifecycle database and a private capability registry, then stops
    the worker before returning.
    """

    validation = validate_plugin_package(root)
    if validation.manifest is None or validation.errors:
        raise PluginEcosystemError(
            "INVALID_PLUGIN_PACKAGE",
            "plugin package failed static validation",
            status_code=422,
            details={"validation": validation.to_dict()},
        )
    manifest = validation.manifest
    tools = [
        capability
        for capability in manifest.capabilities
        if _capability_type(capability) == CapabilityType.TOOL.value
        and capability.entry_point
    ]
    if not tools:
        raise PluginEcosystemError(
            "NO_SUPPORTED_CAPABILITIES",
            "plugin has no tool capability with an entry_point for the R83 host",
            status_code=422,
            details={"validation": validation.to_dict()},
        )
    selected = capability_name or tools[0].name
    if selected not in {capability.name for capability in tools}:
        raise PluginEcosystemError(
            "PLUGIN_CAPABILITY_NOT_FOUND",
            f"tool capability is not declared by this plugin: {selected!r}",
            status_code=404,
            details={"capabilities": [capability.name for capability in tools]},
        )
    payload = dict(arguments or {})
    plugin_config = dict(config or {})

    from backend.plugins.host import PluginHostError, PluginHostManager
    from backend.plugins.lifecycle import PluginLifecycleError, PluginLifecycleManager
    from backend.plugins.registry import CapabilityRegistry

    with tempfile.TemporaryDirectory(prefix="sage-plugin-dev-") as temp_dir:
        manager = PluginLifecycleManager(db_path=Path(temp_dir) / "plugins.db")
        host = PluginHostManager(registry=CapabilityRegistry())
        try:
            record = manager.install(manifest, validation.root.resolve())
            if plugin_config:
                record = manager.update_config(manifest.name, plugin_config)
            record = manager.enable(manifest.name)
            host.start(record)
            result = host.invoke(manifest.name, selected, payload)
            runtime = host.status(manifest.name).to_dict()
            return PluginDevResult(
                root=validation.root,
                manifest=manifest,
                capability=selected,
                arguments=payload,
                result=result,
                runtime=runtime,
                record=_model_to_dict(record),
            )
        except PluginHostError as exc:
            raise PluginEcosystemError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                details={"runtime": host.status(manifest.name).to_dict()},
            ) from exc
        except PluginLifecycleError as exc:
            raise PluginEcosystemError(
                "PLUGIN_LIFECYCLE_ERROR",
                str(exc),
                status_code=422,
            ) from exc
        finally:
            host.shutdown_all()
            manager.close()


__all__ = [
    "TEMPLATE_NAMES",
    "PluginDevResult",
    "PluginEcosystemError",
    "PluginPackageValidation",
    "PluginValidationIssue",
    "ScaffoldOptions",
    "ScaffoldResult",
    "list_templates",
    "run_plugin_dev",
    "scaffold_plugin",
    "validate_plugin_package",
]
