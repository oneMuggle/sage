# ruff: noqa: UP006, UP007, UP035
"""Sage harness 配置 CLI（R81）。

用法::

    python -m backend.cli.harness presets [--json]
    python -m backend.cli.harness dump-config [--workspace PATH]
        [--user-home PATH] [--preset NAME] [--patch FILE] [--json]
    python -m backend.cli.harness check [--workspace PATH]
        [--user-home PATH] [--preset NAME] [--patch FILE] [--json]

``dump-config`` 导出三层文件、环境变量与临时 patch 合并后的实际结果，
包括每个 bundle 被选/被跳过的原因；``check`` 使用严格模式，坏配置以
退出码 1 失败。CLI 参数/文件错误使用退出码 2。
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
    resolved_view,
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

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口。成功返回 0；strict 校验失败 1；CLI/文件错误 2。"""
    args = build_parser().parse_args(argv)

    try:
        if args.command == "presets":
            if args.json:
                _print_json(presets_view())
            else:
                _emit(_render_presets())
            return 0

        config, names = _load_for_cli(args, strict=args.command == "check")
    except HarnessConfigError as exc:
        _emit(f"错误：{exc}", stderr=True)
        return 1 if args.command == "check" else 2

    view = resolved_view(config, names)
    if args.command == "check":
        if args.json:
            _print_json({"ok": True, "config": view})
        else:
            selected_count = len(view["bundles"]["selected"])
            _emit(f"OK: preset={config.preset} selected_bundles={selected_count}")
        return 0

    if args.json:
        _print_json(view)
    else:
        _emit(_render_resolved(view))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
