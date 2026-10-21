# ruff: noqa: UP006, UP007, UP035
"""Sage plugin ecosystem CLI (R86).

Use as ``python -m backend.cli.plugin ...`` in a Sage checkout. Packaged
``sage plugin`` wrappers can forward the same arguments. The CLI makes four
explicit operations available: scaffold, statically validate, run a one-shot
out-of-process dev invoke, and build/validate/search a static index.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from backend.plugins.index_catalog import (
    build_plugin_index,
    load_plugin_index,
    search_plugin_index,
    validate_plugin_index,
    write_plugin_index,
)
from backend.plugins.scaffold import (
    TEMPLATE_NAMES,
    ScaffoldOptions,
    list_templates,
    run_plugin_dev,
    scaffold_plugin,
    validate_plugin_package,
)
from backend.plugins.scaffold_templates import PluginEcosystemError

_INPUT_ERROR_CODES = {
    "INVALID_SCAFFOLD_OPTIONS",
    "PLUGIN_INDEX_INVALID",
    "PLUGIN_OUTPUT_CONFLICT",
    "PLUGIN_OUTPUT_EXISTS",
    "PLUGIN_OUTPUT_NOT_DIRECTORY",
    "PLUGIN_ROOT_NOT_FOUND",
    "PLUGIN_SOURCE_SUBDIR_UNKNOWN",
    "PLUGIN_SOURCE_URL_REQUIRED",
    "UNKNOWN_CAPABILITY_TYPE",
    "UNKNOWN_PLUGIN_TEMPLATE",
}


class _CliInputError(ValueError):
    """A user-supplied CLI file or JSON value is invalid."""


def _emit(text: str, *, stderr: bool = False) -> None:
    print(text, file=sys.stderr if stderr else sys.stdout)  # noqa: T201 - CLI output


def _print_json(payload: Any, *, stderr: bool = False) -> None:
    _emit(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        stderr=stderr,
    )


def _json_file(path: Path, label: str) -> Dict[str, Any]:
    try:
        loaded = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _CliInputError(f"could not read {label} JSON file {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise _CliInputError(f"{label} JSON must be an object: {path}")
    return loaded


def _json_object_arg(
    inline: Optional[str],
    path: Optional[Path],
    label: str,
) -> Dict[str, Any]:
    if path is not None:
        return _json_file(path, label)
    if inline is None:
        return {}
    try:
        loaded = json.loads(inline)
    except json.JSONDecodeError as exc:
        raise _CliInputError(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise _CliInputError(f"{label} JSON must be an object")
    return loaded


def _render_templates() -> str:
    lines = []
    for template in list_templates():
        lines.append(
            "{name} [{maturity}] {capability_type}: {description}".format(**template)
        )
    return "\n".join(lines)


def _render_scaffold(result: Any) -> str:
    payload = result.to_dict()
    lines = [
        f"Created {result.manifest.name} v{result.manifest.version}",
        f"root: {result.root}",
        "template: {name} ({maturity})".format(**payload["template"]),
        "files:",
    ]
    lines.extend(f"  - {name}" for name in result.files)
    lines.extend(
        [
            "next:",
            f"  python -m backend.cli.plugin validate {result.root} --strict",
        ]
    )
    if result.template == "tool":
        lines.append(
            "  python -m backend.cli.plugin dev {} --arguments-file {}".format(
                result.root,
                result.root / "examples" / "request.json",
            )
        )
    return "\n".join(lines)


def _render_validation(validation: Any) -> str:
    if validation.manifest is not None:
        lines = [
            f"plugin: {validation.manifest.name} v{validation.manifest.version}",
            f"root: {validation.root}",
            "permissions: " + (", ".join(validation.permissions) or "(none)"),
        ]
    else:
        lines = [f"root: {validation.root}", "plugin: (unreadable)"]
    lines.append(f"ok: {str(validation.ok).lower()}")
    lines.append("issues:")
    if validation.issues:
        for issue in validation.issues:
            location = f" [{issue.path}]" if issue.path else ""
            lines.append(f"  - {issue.severity} {issue.code}{location}: {issue.message}")
    else:
        lines.append("  - (none)")
    return "\n".join(lines)


def _render_dev(result: Any) -> str:
    runtime_state = result.runtime.get("state")
    return "\n".join(
        [
            f"plugin: {result.manifest.name} v{result.manifest.version}",
            f"capability: {result.capability}",
            f"runtime: {runtime_state}",
            "result: " + json.dumps(result.result, ensure_ascii=False, default=str),
        ]
    )


def _render_index_validation(validation: Any) -> str:
    lines = [
        f"index: {validation.path}",
        f"plugins: {len(validation.index.plugins) if validation.index is not None else 0}",
        f"ok: {str(validation.ok).lower()}",
        "issues:",
    ]
    if validation.issues:
        for issue in validation.issues:
            plugin = f" [{issue.plugin}]" if issue.plugin else ""
            lines.append(f"  - {issue.severity} {issue.code}{plugin}: {issue.message}")
    else:
        lines.append("  - (none)")
    return "\n".join(lines)


def _render_search(results: Sequence[Dict[str, Any]]) -> str:
    if not results:
        return "No plugins matched."
    lines = []
    for result in results:
        permissions = ", ".join(result["permissions"]) or "none"
        lines.append(
            "{} v{} - {} (permissions: {})".format(
                result["name"],
                result["version"],
                result["display_name"],
                permissions,
            )
        )
        if result["description"]:
            lines.append(f"  {result['description']}")
    return "\n".join(lines)


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="output machine-readable JSON")


def _add_index_parser(subparsers: Any) -> None:
    index = subparsers.add_parser("index", help="build, validate, or search a static plugin index")
    index_sub = index.add_subparsers(dest="index_command")

    build = index_sub.add_parser("build", help="build index.json from plugin roots")
    build.add_argument("roots", nargs="+", type=Path, help="plugin roots or collections")
    build.add_argument("--output", type=Path, help="index output path (default: stdout)")
    build.add_argument(
        "--source-kind",
        choices=("local", "git"),
        default="local",
        help="source locator to record for each plugin",
    )
    build.add_argument("--source-url", help="HTTPS git repository URL")
    build.add_argument("--source-ref", default="main", help="git ref (default: main)")
    build.add_argument(
        "--base-dir",
        type=Path,
        help="base for local paths/git subdirs (default: current directory)",
    )
    _add_json_argument(build)

    validate = index_sub.add_parser("validate", help="validate a static plugin index")
    validate.add_argument("file", type=Path, help="index.json path")
    validate.add_argument(
        "--check-local",
        action="store_true",
        help="also check local/git-subdir manifests against the index",
    )
    validate.add_argument(
        "--base-dir",
        type=Path,
        help="checkout base for --check-local (default: cwd for git, index directory for local)",
    )
    _add_json_argument(validate)

    search = index_sub.add_parser("search", help="search a static plugin index offline")
    search.add_argument("file", type=Path, help="index.json path")
    search.add_argument("query", nargs="?", default="", help="space-separated search terms")
    search.add_argument("--capability-type", help="filter by capability type")
    search.add_argument("--permission", help="filter by exact declared permission")
    _add_json_argument(search)


def build_parser() -> argparse.ArgumentParser:
    """Build the plugin CLI parser for execution and tests."""

    parser = argparse.ArgumentParser(
        prog="sage plugin",
        description="Scaffold, validate, smoke-test, and index Sage plugins.",
    )
    subparsers = parser.add_subparsers(dest="command")

    templates = subparsers.add_parser("templates", help="list scaffold templates")
    _add_json_argument(templates)

    init = subparsers.add_parser("init", help="create a new plugin package")
    init.add_argument("name", help="plugin name, such as acme-echo")
    init.add_argument(
        "--template",
        choices=TEMPLATE_NAMES,
        default="tool",
        help="scaffold template (default: tool)",
    )
    init.add_argument("--output", type=Path, help="output directory (default: ./<name>)")
    init.add_argument("--display-name", help="human-readable plugin name")
    init.add_argument("--author", default="", help="plugin author")
    init.add_argument("--description", help="plugin description")
    init.add_argument("--version", default="0.1.0", help="initial semantic version")
    init.add_argument(
        "--force",
        action="store_true",
        help="overwrite generated files in an existing directory",
    )
    _add_json_argument(init)

    validate = subparsers.add_parser("validate", help="statically validate a plugin package")
    validate.add_argument("path", type=Path, help="plugin package directory")
    validate.add_argument(
        "--strict",
        action="store_true",
        help="treat validation warnings as failures",
    )
    _add_json_argument(validate)

    dev = subparsers.add_parser(
        "dev",
        help="run one explicit out-of-process tool invoke (executes plugin code)",
    )
    dev.add_argument("path", type=Path, help="plugin package directory")
    dev.add_argument("--capability", help="tool capability name (default: first tool)")
    arguments_group = dev.add_mutually_exclusive_group()
    arguments_group.add_argument("--arguments", help="tool arguments as a JSON object")
    arguments_group.add_argument(
        "--arguments-file",
        type=Path,
        help="file containing tool arguments as a JSON object",
    )
    config_group = dev.add_mutually_exclusive_group()
    config_group.add_argument("--config", help="plugin config as a JSON object")
    config_group.add_argument(
        "--config-file",
        type=Path,
        help="file containing plugin config as a JSON object",
    )
    _add_json_argument(dev)

    _add_index_parser(subparsers)
    return parser


def _run_index(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.index_command == "build":
        result = build_plugin_index(
            args.roots,
            source_kind=args.source_kind,
            source_url=args.source_url,
            source_ref=args.source_ref,
            base_dir=args.base_dir,
        )
        output = write_plugin_index(result.index, args.output) if args.output else None
        if args.json:
            payload = result.to_dict()
            payload["output"] = str(output) if output is not None else None
            _print_json(payload)
        elif output is None:
            _emit(result.index.to_json(indent=2))
        else:
            warnings = sum(len(item.warnings) for item in result.validations)
            _emit(
                f"Wrote {len(result.index.plugins)} plugin(s) to {output} ({warnings} package warning(s))"
            )
        return 0

    if args.index_command == "validate":
        validation = validate_plugin_index(
            args.file,
            check_local=args.check_local,
            base_dir=args.base_dir,
        )
        if args.json:
            _print_json(validation.to_dict())
        else:
            _emit(_render_index_validation(validation))
        return 0 if validation.ok else 1

    if args.index_command == "search":
        results = search_plugin_index(
            load_plugin_index(args.file),
            args.query,
            capability_type=args.capability_type,
            permission=args.permission,
        )
        if args.json:
            _print_json({"ok": True, "results": results})
        else:
            _emit(_render_search(results))
        return 0

    parser.print_help()
    return 2


def _error_exit_code(exc: PluginEcosystemError) -> int:
    return 2 if exc.code in _INPUT_ERROR_CODES else 1


def main(argv: Optional[Sequence[str]] = None) -> int:  # noqa: PLR0911 - CLI dispatch
    """CLI entry point: 0 success, 1 validation/business failure, 2 input error."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "templates":
            if args.json:
                _print_json({"ok": True, "templates": list_templates()})
            else:
                _emit(_render_templates())
            return 0

        if args.command == "init":
            result = scaffold_plugin(
                ScaffoldOptions(
                    name=args.name,
                    output_dir=args.output,
                    template=args.template,
                    display_name=args.display_name,
                    author=args.author,
                    description=args.description,
                    version=args.version,
                    force=args.force,
                )
            )
            if args.json:
                _print_json(result.to_dict())
            else:
                _emit(_render_scaffold(result))
            return 0

        if args.command == "validate":
            validation = validate_plugin_package(args.path, strict=args.strict)
            if args.json:
                _print_json(validation.to_dict())
            else:
                _emit(_render_validation(validation))
            return 0 if validation.ok else 1

        if args.command == "dev":
            result = run_plugin_dev(
                args.path,
                capability_name=args.capability,
                arguments=_json_object_arg(
                    args.arguments,
                    args.arguments_file,
                    "arguments",
                ),
                config=_json_object_arg(args.config, args.config_file, "config"),
            )
            if args.json:
                _print_json(result.to_dict())
            else:
                _emit(_render_dev(result))
            return 0

        if args.command == "index":
            return _run_index(args, parser)

    except PluginEcosystemError as exc:
        if getattr(args, "json", False):
            _print_json(exc.to_dict(), stderr=True)
        else:
            _emit(f"Error [{exc.code}]: {exc.message}", stderr=True)
        return _error_exit_code(exc)
    except _CliInputError as exc:
        if getattr(args, "json", False):
            _print_json(
                {"ok": False, "error": "INVALID_CLI_INPUT", "detail": str(exc)},
                stderr=True,
            )
        else:
            _emit(f"Error: {exc}", stderr=True)
        return 2
    except (OSError, ValueError) as exc:
        if getattr(args, "json", False):
            _print_json(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "detail": str(exc),
                },
                stderr=True,
            )
        else:
            _emit(f"Error: {type(exc).__name__}: {exc}", stderr=True)
        return 2

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
