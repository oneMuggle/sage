# ruff: noqa: T201
"""Offline component package CLI.

Human mode prints Chinese status lines. ``--json`` mode emits one JSON object
per line so the Electron main process can turn progress into IPC events.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from backend.services.components.errors import ComponentError
from backend.services.components.models import ComponentManifest, InstalledComponent
from backend.services.components.service import ComponentService


def _configure_encoding() -> None:
    """Force UTF-8 on piped stdout/stderr (Win7 cp936/cp1252 consoles)."""
    for stream in (sys.stdout, sys.stderr):
        if stream.isatty():
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(AttributeError, ValueError):
            reconfigure(encoding="utf-8", line_buffering=True)


def _emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _progress_printer(as_json: bool) -> Callable[[str, str, int, int], None]:
    def report(phase: str, message: str, done: int, total: int) -> None:
        if as_json:
            _emit(
                {
                    "event": "progress",
                    "phase": phase,
                    "message": message,
                    "done": done,
                    "total": total,
                }
            )
            return
        if total:
            print(f"[{phase}] {message} ({done}/{total})")
        else:
            print(f"[{phase}] {message}")

    return report


def _component_summary(component: InstalledComponent) -> Dict[str, Any]:
    return {
        "id": component.id,
        "name": component.name,
        "version": component.version,
        "target": component.target,
        "installedAt": component.installed_at,
        "fileCount": len(component.files),
        "totalBytes": component.total_bytes,
        "sourcePackage": component.source_package,
        "signatureVerified": component.signature_verified,
    }


def _manifest_summary(manifest: ComponentManifest) -> Dict[str, Any]:
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "branch": manifest.branch,
        "python": manifest.python,
        "arch": manifest.arch,
        "target": manifest.target,
        "fileCount": len(manifest.files),
        "totalBytes": manifest.total_bytes,
    }


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        print()
        return False
    return answer in ("y", "yes", "是")


def _result(as_json: bool, payload: Dict[str, Any]) -> None:
    if as_json:
        _emit({"event": "result", "ok": True, **payload})
        return
    action = payload.get("action", "")
    if action == "list":
        installed = payload.get("installed", [])
        if not installed:
            print("未安装任何离线组件。")
        for item in installed:
            print(
                f"- {item['name']} ({item['id']}) {item['version']} "
                f"{item['target']} {item['totalBytes']} bytes"
            )
        discovered = payload.get("discovered", [])
        if discovered:
            print("发现可导入的组件包：")
            for item in discovered:
                print(f"  {item['path']}")
    elif action == "scan":
        packages = payload.get("packages", [])
        if not packages:
            print("未发现组件包。")
        for item in packages:
            if item.get("error"):
                print(f"  ✗ {item['path']}: {item['error']}")
            else:
                print(f"  ✓ {item['id']} {item['version']} ({item['path']})")
    elif action == "verify":
        component = payload.get("component", {})
        print(
            f"校验通过：{component.get('name')} {component.get('version')} "
            f"({component.get('fileCount')} 个文件)"
        )
    elif action == "import":
        component = payload.get("component", {})
        print(
            f"导入完成：{component.get('name')} {component.get('version')}。"
            "请重启 Sage 后生效。"
        )
    elif action == "remove":
        print(f"已卸载组件：{payload.get('componentId')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backend.cli.components",
        description="Sage 离线组件包管理（验证/导入/卸载/扫描）",
    )
    sub = parser.add_subparsers(dest="action")

    p_list = sub.add_parser("list", help="列出已安装组件与可发现的组件包")
    p_list.add_argument("--json", action="store_true", dest="as_json")

    p_scan = sub.add_parser("scan", help="扫描组件包目录")
    p_scan.add_argument("--dir", action="append", default=None)
    p_scan.add_argument("--json", action="store_true", dest="as_json")

    p_verify = sub.add_parser("verify", help="校验组件包签名与文件")
    p_verify.add_argument("package")
    p_verify.add_argument("--json", action="store_true", dest="as_json")

    p_import = sub.add_parser("import", help="导入组件包")
    p_import.add_argument("package")
    p_import.add_argument("--json", action="store_true", dest="as_json")
    p_import.add_argument("--yes", action="store_true")

    p_remove = sub.add_parser("remove", help="卸载组件")
    p_remove.add_argument("component_id")
    p_remove.add_argument("--json", action="store_true", dest="as_json")
    p_remove.add_argument("--yes", action="store_true")
    return parser


def _make_service(as_json: bool) -> ComponentService:
    return ComponentService.from_environment(progress=_progress_printer(as_json))


def main(argv: Optional[Sequence[str]] = None) -> int:  # noqa: PLR0911 — one branch per action
    _configure_encoding()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not args.action:
        parser.print_help()
        return 2
    as_json = bool(getattr(args, "as_json", False))
    try:
        if args.action == "list":
            service = _make_service(as_json)
            payload = {
                "action": "list",
                "installed": [_component_summary(item) for item in service.list_installed()],
                "discovered": [item.to_dict() for item in service.scan()],
            }
            _result(as_json, payload)
            return 0

        if args.action == "scan":
            service = _make_service(as_json)
            dirs = [Path(item) for item in args.dir] if args.dir else None
            payload = {
                "action": "scan",
                "packages": [item.to_dict() for item in service.scan(dirs)],
            }
            _result(as_json, payload)
            return 0

        if args.action == "verify":
            service = _make_service(as_json)
            manifest = service.verify_package(Path(args.package), full=True)
            _result(
                as_json,
                {"action": "verify", "component": _manifest_summary(manifest)},
            )
            return 0

        if args.action == "import":
            service = _make_service(as_json)
            component = service.install(Path(args.package))
            _result(
                as_json,
                {"action": "import", "component": _component_summary(component)},
            )
            return 0

        if args.action == "remove":
            if not args.yes and not _confirm(f"确认卸载组件 {args.component_id}？"):
                if as_json:
                    _emit(
                        {
                            "event": "result",
                            "ok": False,
                            "code": "cancelled",
                            "error": "用户取消",
                        }
                    )
                else:
                    print("已取消。")
                return 2
            service = _make_service(as_json)
            removed = service.remove(args.component_id)
            if not removed:
                raise ComponentError(
                    f"组件未安装：{args.component_id}", code="not_installed"
                )
            _result(as_json, {"action": "remove", "componentId": args.component_id})
            return 0

        parser.print_help()
        return 2
    except ComponentError as exc:
        if as_json:
            _emit(
                {
                    "event": "result",
                    "ok": False,
                    "code": exc.code,
                    "error": str(exc),
                }
            )
        else:
            print(f"错误: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 — CLI 顶层兜底，避免堆栈淹没可读错误
        if as_json:
            _emit(
                {
                    "event": "result",
                    "ok": False,
                    "code": "unexpected_error",
                    "error": str(exc),
                }
            )
        else:
            print(f"错误: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
