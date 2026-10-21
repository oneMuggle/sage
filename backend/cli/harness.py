# ruff: noqa: UP006, UP007, UP035
"""Sage harness 配置 CLI（R81）。

用法::

    python -m backend.cli.harness presets [--json]
    python -m backend.cli.harness dump-config [--workspace PATH]
        [--user-home PATH] [--preset NAME] [--patch FILE] [--json]
    python -m backend.cli.harness check [--workspace PATH]
        [--user-home PATH] [--preset NAME] [--patch FILE] [--json]
    python -m backend.cli.harness files export|status|verify|update-lock|diff|snapshot|snapshots|rollback ...

``dump-config`` 导出三层文件、环境变量与临时 patch 合并后的实际结果，
包括每个 bundle 被选/被跳过的原因；``check`` 使用严格模式，坏配置或
已采用 harness lock 校验失败以退出码 1 失败。``files`` 子命令管理
R84 的 fileized harness、lock、snapshot 与 rollback。CLI 参数/文件
错误使用退出码 2。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from backend.application.kernel.harness_config import (
    PRESET_NAMES,
    HarnessConfig,
    HarnessConfigError,
    load_harness_config,
    presets_view,
    project_harness_files_dir,
    resolved_view,
    user_harness_files_dir,
)
from backend.application.kernel.harness_files import (
    HarnessFilesError,
    assert_adopted_harness_files_valid,
    update_harness_lock,
)
from backend.application.kernel.harness_snapshots import (
    create_harness_snapshot,
    harness_diff_view,
    harness_status_view,
    list_harness_snapshots,
    rollback_harness_files,
    write_harness_files,
)


def _known_bundle_names() -> Tuple[str, ...]:
    """延迟加载工具声明，让 ``presets`` 子命令保持轻量。"""
    from backend.tools.tool_bundles import bundle_names

    return bundle_names()


def _read_patch(path_text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path_text:
        return None

    path = Path(path_text).expanduser()
    try:
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 —— 转成稳定的 CLI 错误
        raise HarnessConfigError(
            f"patch 文件读取失败：{path}（{type(exc).__name__}: {exc}）"
        ) from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise HarnessConfigError(f"patch 文件顶层必须是映射：{path}")
    return loaded


def _combined_patch(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    patch = _read_patch(getattr(args, "patch", None))
    preset = getattr(args, "preset", None)
    if preset:
        combined = dict(patch or {})
        combined["preset"] = preset
        return combined
    return patch


def _load_for_cli(
    args: argparse.Namespace,
    *,
    strict: bool,
) -> Tuple[HarnessConfig, Tuple[str, ...]]:
    names = _known_bundle_names()
    config = load_harness_config(
        workspace=getattr(args, "workspace", None),
        user_home=getattr(args, "user_home", None),
        patch=_combined_patch(args),
        known_bundles=names,
        strict=strict,
    )
    return config, names


def _emit(text: str, *, stderr: bool = False) -> None:
    """CLI 的唯一 stdout/stderr 出口。"""
    print(text, file=sys.stderr if stderr else sys.stdout)  # noqa: T201 —— CLI output


def _print_json(payload: Any) -> None:
    _emit(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _render_presets() -> str:
    lines = []
    for preset in presets_view():
        lines.append(f"{preset['name']} — {preset['description']}")
        excluded = ", ".join(preset["excluded_bundles"]) or "(none)"
        lines.append(f"  excluded bundles: {excluded}")
        flags = json.dumps(preset["flags"], ensure_ascii=False, sort_keys=True)
        lines.append(f"  flags: {flags}")
    return "\n".join(lines)


def _render_resolved(view: Dict[str, Any]) -> str:
    bundles = view["bundles"]
    selected = bundles["selected"]
    skipped = bundles["skipped"]
    lines = [
        f"preset: {view['preset']}",
        f"description: {view['description']}",
        "flags: " + json.dumps(view["flags"], ensure_ascii=False, sort_keys=True),
        "bundle overrides: "
        + json.dumps(view["bundle_overrides"], ensure_ascii=False, sort_keys=True),
        "sources:",
    ]
    lines.extend(f"  - {source}" for source in view["sources"])

    lines.append(f"selected bundles ({len(selected)}):")
    lines.extend(f"  - {name}" for name in selected)

    lines.append(f"skipped bundles ({len(skipped)}):")
    if skipped:
        lines.extend(f"  - {item['name']} ({item['reason']})" for item in skipped)
    else:
        lines.append("  - (none)")

    lines.append("warnings:")
    if view["warnings"]:
        lines.extend(f"  - {warning}" for warning in view["warnings"])
    else:
        lines.append("  - (none)")
    return "\n".join(lines)


def _files_root(args: argparse.Namespace) -> Path:
    output = getattr(args, "output", None)
    if output:
        return Path(output).expanduser()
    if getattr(args, "scope", "project") == "user":
        return user_harness_files_dir(getattr(args, "user_home", None))
    return project_harness_files_dir(getattr(args, "workspace", None))


def _render_files_status(view: Dict[str, Any]) -> str:
    counts = view["counts"]
    lines = [
        f"root: {view['root']}",
        "exists: {exists} adopted: {adopted} valid: {valid} enforced: {enforced}".format(
            **view
        ),
        "counts: unchanged={unchanged} modified={modified} missing={missing} added={added}".format(
            **counts
        ),
        "issues:",
    ]
    if view["issues"]:
        lines.extend(
            f"  - {issue['code']}" + (f": {issue['path']}" if issue["path"] else "")
            for issue in view["issues"]
        )
    else:
        lines.append("  - (none)")
    lines.append("snapshots:")
    if view["snapshots"]:
        lines.extend(f"  - {snapshot['id']}" for snapshot in view["snapshots"])
    else:
        lines.append("  - (none)")
    return "\n".join(lines)


def _render_diff(view: Dict[str, Any]) -> str:
    counts = view["counts"]
    lines = [
        f"root: {view['root']}",
        f"snapshot: {view['snapshot']['id']}",
        "counts: added={added} modified={modified} deleted={deleted} unchanged={unchanged}".format(
            **counts
        ),
    ]
    markers = {"added": "+", "modified": "M", "deleted": "-"}
    if view["entries"]:
        lines.extend(
            f"{markers.get(entry['status'], '?')} {entry['path']}"
            for entry in view["entries"]
        )
    else:
        lines.append("(no changes)")
    for entry in view["entries"]:
        patch = entry.get("patch")
        if patch:
            lines.append("")
            lines.append(patch.rstrip())
    return "\n".join(lines)


def _render_snapshots(snapshots: Sequence[Any]) -> str:
    if not snapshots:
        return "(no snapshots)"
    return "\n".join(
        f"{snapshot.snapshot_id} created={snapshot.created_at} files={snapshot.file_count} bytes={snapshot.total_size}"
        for snapshot in snapshots
    )


def _run_files(args: argparse.Namespace) -> int:  # noqa: PLR0911 — CLI 子命令分发
    root = _files_root(args)
    command = args.files_command

    if command == "export":
        from backend.cli.harness_export import collect_harness_file_specs

        specs = collect_harness_file_specs(
            workspace=getattr(args, "workspace", None),
            user_home=getattr(args, "user_home", None),
            scope=args.scope,
        )
        result = write_harness_files(
            root,
            specs,
            force=args.force,
            create_snapshot=not args.no_snapshot,
            startup_enforced=not args.no_enforce_startup,
        )
        if args.json:
            _print_json(result)
        else:
            snapshot = result.get("snapshot") or {}
            suffix = f" snapshot={snapshot.get('id')}" if snapshot else ""
            _emit(
                f"OK: exported {result['file_count']} harness files to {result['root']}{suffix}"
            )
        return 0

    if command in ("status", "verify"):
        view = harness_status_view(root)
        if args.json:
            _print_json(view)
        else:
            _emit(_render_files_status(view))
        if command == "verify":
            return 0 if view["adopted"] and view["valid"] else 1
        return 0

    if command == "update-lock":
        lock = update_harness_lock(root)
        payload = lock.to_dict()
        if args.json:
            _print_json(payload)
        else:
            _emit(
                f"OK: updated harness lock files={len(lock.files)} content_sha256={lock.content_sha256}"
            )
        return 0

    if command == "diff":
        view = harness_diff_view(root, args.snapshot, include_patch=args.patch)
        if args.json:
            _print_json(view)
        else:
            _emit(_render_diff(view))
        return 0

    if command == "snapshot":
        snapshot = create_harness_snapshot(root, args.name)
        if args.json:
            _print_json(snapshot.to_dict())
        else:
            _emit(f"OK: created harness snapshot {snapshot.snapshot_id}")
        return 0

    if command == "snapshots":
        snapshots = list_harness_snapshots(root)
        if args.json:
            _print_json([snapshot.to_dict() for snapshot in snapshots])
        else:
            _emit(_render_snapshots(snapshots))
        return 0

    if command == "rollback":
        result = rollback_harness_files(
            root,
            args.snapshot,
            create_pre_snapshot=not args.no_pre_snapshot,
        )
        if args.json:
            _print_json(result)
        else:
            _emit(
                "OK: rolled back harness files to "
                f"{result['snapshot']['id']} restored={result['restored_files']}"
            )
        return 0

    raise HarnessFilesError(f"unknown files command: {command}")


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        help="项目根目录（缺省：SAGE_WORKSPACE 或当前目录）",
    )
    parser.add_argument(
        "--user-home",
        help="用户主目录（缺省：SAGE_HARNESS_HOME 或系统主目录）",
    )
    parser.add_argument(
        "--preset",
        choices=PRESET_NAMES,
        help="临时覆盖 preset（优先级高于文件与 SAGE_HARNESS_PRESET）",
    )
    parser.add_argument(
        "--patch",
        help="最高层 YAML patch 文件；--preset 若同时给出则覆盖其中 preset",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")


def _add_files_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        help="项目根目录（缺省：SAGE_WORKSPACE 或当前目录）",
    )
    parser.add_argument(
        "--user-home",
        help="用户主目录（缺省：SAGE_HARNESS_HOME 或系统主目录）",
    )
    parser.add_argument(
        "--scope",
        choices=("project", "user"),
        default="project",
        help="文件集作用域（默认 project）",
    )
    parser.add_argument("--output", help="显式 fileized harness 根目录")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")


def _add_files_parser(subparsers: Any) -> None:
    files = subparsers.add_parser("files", help="管理 fileized harness、lock 与 snapshot")
    files_sub = files.add_subparsers(dest="files_command", required=True)

    export = files_sub.add_parser("export", help="导出 8 个 harness 行为面")
    _add_files_arguments(export)
    export.add_argument("--force", action="store_true", help="覆盖已有托管文件集")
    export.add_argument("--no-snapshot", action="store_true", help="不创建 snapshot")
    export.add_argument(
        "--no-enforce-startup",
        action="store_true",
        help="生成仅供检查的 lock，不在后端启动时强制校验",
    )

    for name, help_text in (
        ("status", "查看 lock 与 snapshot 状态"),
        ("verify", "校验 fileized harness lock"),
        ("update-lock", "按当前托管文件刷新 lock"),
        ("snapshots", "列出 snapshot"),
    ):
        child = files_sub.add_parser(name, help=help_text)
        _add_files_arguments(child)

    diff = files_sub.add_parser("diff", help="查看当前文件集相对 snapshot 的差异")
    _add_files_arguments(diff)
    diff.add_argument("--snapshot", help="snapshot id（缺省：最新）")
    diff.add_argument("--patch", action="store_true", help="附带 unified diff")

    snapshot = files_sub.add_parser("snapshot", help="创建 snapshot")
    _add_files_arguments(snapshot)
    snapshot.add_argument("--name", help="snapshot id（缺省：时间戳）")

    rollback = files_sub.add_parser("rollback", help="回滚到 snapshot")
    _add_files_arguments(rollback)
    rollback.add_argument("--snapshot", help="snapshot id（缺省：最新）")
    rollback.add_argument(
        "--no-pre-snapshot",
        action="store_true",
        help="不为回滚前状态创建 snapshot",
    )


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器（单独暴露供测试）。"""
    parser = argparse.ArgumentParser(
        prog="python -m backend.cli.harness",
        description="查看、导出与校验 Sage 工具装配的 harness 配置。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    presets = subparsers.add_parser("presets", help="列出四预设及其 bundle 排除集")
    presets.add_argument("--json", action="store_true", help="输出机器可读 JSON")

    dump = subparsers.add_parser("dump-config", help="导出合并后的配置与 bundle 选择")
    _add_config_arguments(dump)

    check = subparsers.add_parser("check", help="严格校验 harness 配置")
    _add_config_arguments(check)

    _add_files_parser(subparsers)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:  # noqa: PLR0911 — CLI 顶层分发与错误码
    """CLI 入口。成功返回 0；strict 校验失败 1；CLI/文件错误 2。"""
    args = build_parser().parse_args(argv)

    try:
        if args.command == "presets":
            if args.json:
                _print_json(presets_view())
            else:
                _emit(_render_presets())
            return 0

        if args.command == "files":
            return _run_files(args)

        config, names = _load_for_cli(args, strict=args.command == "check")
        file_checks = []
        if args.command == "check":
            file_checks = assert_adopted_harness_files_valid(
                workspace=getattr(args, "workspace", None),
                user_home=getattr(args, "user_home", None),
            )
    except HarnessConfigError as exc:
        _emit(f"错误：{exc}", stderr=True)
        return 1 if args.command == "check" else 2
    except HarnessFilesError as exc:
        _emit(f"错误：{exc}", stderr=True)
        return 1 if args.command == "check" else 2
    except (OSError, ValueError) as exc:
        _emit(f"错误：{type(exc).__name__}: {exc}", stderr=True)
        return 2

    view = resolved_view(config, names)
    if args.command == "check":
        harness_files = [
            {
                "root": item.root,
                "valid": item.valid,
                "enforced": item.enforced,
                "counts": dict(item.counts),
            }
            for item in file_checks
        ]
        if args.json:
            _print_json({"ok": True, "config": view, "harness_files": harness_files})
        else:
            selected_count = len(view["bundles"]["selected"])
            _emit(
                f"OK: preset={config.preset} selected_bundles={selected_count} "
                f"harness_locks={len(harness_files)}"
            )
        return 0

    if args.json:
        _print_json(view)
    else:
        _emit(_render_resolved(view))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
