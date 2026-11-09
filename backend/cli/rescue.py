# ruff: noqa: T201, PLR0911, PLR0912, PLR0915
"""Sage Rescue CLI —— 前端不可用时的一体化修复/配置入口。

用法::

    python -m backend.cli.rescue                 # 交互式 REPL（中文编号菜单）
    python -m backend.cli.rescue diag [--json]
    python -m backend.cli.rescue config list|add|update|remove|test|use|import|export
    python -m backend.cli.rescue repair cache|window|logs|port|config|db
    python -m backend.cli.rescue report [--include-crashdumps] [--include-hostname]
    python -m backend.cli.rescue security detect|stop|disable|restore|plan
    python -m backend.cli.rescue safe-mode status|set <0-3>|off
    python -m backend.cli.rescue allowlist [--output PATH]

设计约束：

- 不依赖 Electron / uvicorn；所有操作通过 ``backend.services.rescue.*`` 完成；
- 交互模式按控制台代码页输出；管道模式强制 UTF-8（供 Electron 解析）；
- 所有破坏性操作必须先确认（``--yes`` 可跳过，仅限脚本/对话框调用）；
- 退出码：0 = OK，1 = 有警告/部分失败，2 = 有严重错误/未确认。
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import getpass
import json
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================
# 输出 / 交互辅助
# ============================================================


def _configure_encoding() -> None:
    """TTY 保持系统编码（Win7 中文控制台 cp936）；管道统一 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if stream.isatty():
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(AttributeError, ValueError):
            reconfigure(encoding="utf-8")


def _print(message: str = "") -> None:
    print(message)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt, OSError):
        print()
        return default
    return value or default


def _ask_secret(prompt: str) -> str:
    try:
        return getpass.getpass(f"{prompt}: ").strip()
    except (EOFError, KeyboardInterrupt, OSError):
        print()
        return ""


def _confirm(prompt: str, *, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        # 非交互环境（pytest / 管道 / 被 Electron 调用）视为"未确认"，
        # 绝不默认执行破坏性动作。
        print()
        return False
    return answer in ("y", "yes", "是")


def _banner() -> None:
    from backend.services.rescue.paths import resolve_db_path, resolve_user_data_dir

    _print("Sage 修复工具 (Rescue Doctor)")
    _print(f"平台: {platform.platform()}")
    _print(f"数据目录: {resolve_user_data_dir()}")
    _print(f"数据库: {resolve_db_path()}")
    _print("=" * 64)


# ============================================================
# diag
# ============================================================


def run_diagnostics(*, as_json: bool = False) -> int:
    """运行全部 doctor 检查（复用注册表）。"""
    from backend.cli import doctor as doctor_mod

    doctor_mod._import_all_checks()
    results = [doctor_mod._run_one(cls) for cls in doctor_mod.ALL_CHECKS]
    if as_json:
        _print(doctor_mod._format_json(results))
    else:
        _print(doctor_mod._format_text(results))
    return doctor_mod._exit_code(results)


def cmd_diag(args: argparse.Namespace) -> int:
    return run_diagnostics(as_json=bool(args.as_json))


# ============================================================
# config
# ============================================================


def _print_endpoints(endpoints: List[Dict[str, Any]]) -> None:
    if not endpoints:
        _print("（暂无端点）")
        return
    for ep in endpoints:
        _print(
            "  - {id} | {name} | {baseUrl} | model={modelId} | key={key}".format(
                id=ep.get("id", "?"),
                name=ep.get("name", ""),
                baseUrl=ep.get("baseUrl", ""),
                modelId=ep.get("modelId", ""),
                key="已配置" if ep.get("hasApiKey") else "未配置",
            )
        )


def cmd_config(args: argparse.Namespace) -> int:
    from backend.services.rescue import config_wizard as cw

    action = args.action
    try:
        if action == "list":
            endpoints = cw.list_endpoints()
            if args.as_json:
                _print(json.dumps(endpoints, ensure_ascii=False, indent=2))
            else:
                _print_endpoints(endpoints)
            return 0

        if action == "add":
            endpoint = {
                "baseUrl": args.base_url,
                "apiKey": args.api_key or _ask_secret("API Key（留空表示无）"),
                "modelId": args.model or "",
                "name": args.name or "",
                "protocol": args.protocol,
            }
            result = cw.save_endpoint(endpoint, mode="create", backup=not args.no_backup)
            _print(f"已创建端点: {result['endpoint']['id']} ({result['endpoint']['name']})")
            return 0

        if action == "update":
            if not args.endpoint_id:
                _print("错误: update 需要 --id")
                return 2
            endpoint: Dict[str, Any] = {"id": args.endpoint_id}
            if args.base_url is not None:
                endpoint["baseUrl"] = args.base_url
            if args.api_key is not None:
                endpoint["apiKey"] = args.api_key or _ask_secret("新 API Key（留空保留原值）")
            if args.model is not None:
                endpoint["modelId"] = args.model
            if args.name is not None:
                endpoint["name"] = args.name
            if args.protocol is not None:
                endpoint["protocol"] = args.protocol
            result = cw.save_endpoint(endpoint, mode="update", backup=not args.no_backup)
            _print(f"已更新端点: {result['endpoint']['id']}")
            return 0

        if action == "remove":
            if not args.endpoint_id:
                _print("错误: remove 需要 --id")
                return 2
            if not _confirm(f"确认删除端点 {args.endpoint_id}？", assume_yes=args.yes):
                return 2
            cw.delete_endpoint(args.endpoint_id, backup=not args.no_backup)
            _print(f"已删除端点: {args.endpoint_id}")
            return 0

        if action == "test":
            if not args.endpoint_id:
                _print("错误: test 需要 --id")
                return 2
            endpoint = cw.get_endpoint(args.endpoint_id)
            if endpoint is None:
                _print(f"错误: 端点 {args.endpoint_id} 不存在")
                return 2
            outcome = cw.probe_connectivity(endpoint, timeout_s=args.timeout)
            _print(
                f"连通性: {outcome['category']} (HTTP {outcome['status_code']}) — {outcome['message']}"
            )
            if outcome.get("models"):
                _print("可用模型: " + ", ".join(str(m) for m in outcome["models"][:20]))
            return 0 if outcome["ok"] else 1

        if action == "use":
            if not args.endpoint_id or not args.model:
                _print("错误: use 需要 --id 与 --model")
                return 2
            cw.save_model_selection(
                args.task, args.endpoint_id, args.model, backup=not args.no_backup
            )
            _print(f"已设置 {args.task} = {args.endpoint_id} / {args.model}")
            return 0

        if action == "import":
            if not args.file:
                _print("错误: import 需要 --file")
                return 2
            summary = cw.import_bundle(
                Path(args.file),
                include_secrets=args.include_secrets,
                backup=not args.no_backup,
            )
            _print(
                f"导入完成: 端点 {summary['endpoints_imported']} 个, "
                f"模型选择 {summary['model_selections_imported']} 个"
            )
            return 0

        if action == "export":
            out = Path(args.file or "sage-config-bundle.json")
            cw.export_bundle(out, include_secrets=args.include_secrets)
            _print(f"已导出: {out}")
            if args.include_secrets:
                _print("⚠️ 包内包含明文 API Key，传输后请删除该文件")
            return 0

        _print(f"错误: 未知 config 动作: {action}")
        return 2
    except Exception as exc:  # noqa: BLE001 — CLI 顶层：任何错误都转成用户可读消息
        _print(f"错误: {exc}")
        return 2


# ============================================================
# repair
# ============================================================


def cmd_repair(args: argparse.Namespace) -> int:
    from backend.services.rescue import repair

    action = args.action
    if action == "cache":
        if not _confirm("清理 Chromium 缓存（不影响登录/会话数据）？", assume_yes=args.yes):
            return 2
        result = repair.clear_caches(confirm=True)
    elif action == "window":
        if not _confirm("重置窗口位置/大小？", assume_yes=args.yes):
            return 2
        result = repair.reset_window_state(confirm=True)
    elif action == "logs":
        result = repair.truncate_logs(max_mb=args.max_mb)
    elif action == "port":
        if not _confirm("结束占用 8765 端口的进程？", assume_yes=args.yes):
            return 2
        result = repair.kill_orphan_backend(port=args.port, confirm=True)
    elif action == "config":
        if not _confirm("备份并重置端点/模型配置（会丢失全部端点）？", assume_yes=args.yes):
            return 2
        result = repair.reset_config(confirm=True)
    elif action == "db":
        result = repair.check_db_integrity()
        if not result.get("ok"):
            _print("数据库异常，建议先备份再修复")
    else:
        _print(f"错误: 未知 repair 动作: {action}")
        return 2
    _print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = result.get("ok", True) and not result.get("error") and not result.get("unsupported")
    return 0 if ok else 1


# ============================================================
# report / allowlist
# ============================================================


def cmd_report(args: argparse.Namespace) -> int:
    from backend.services.rescue.support_bundle import collect_support_bundle

    doctor_report = None
    try:
        from backend.cli import doctor as doctor_mod

        doctor_mod._import_all_checks()
        results = [doctor_mod._run_one(cls) for cls in doctor_mod.ALL_CHECKS]
        doctor_report = {
            "checks": [r.to_dict() for r in results],
            "summary": doctor_mod._summarize(results),
        }
    except Exception:
        doctor_report = None
    path = collect_support_bundle(
        doctor_report=doctor_report,
        include_crashdumps=bool(args.include_crashdumps),
        include_hostname=bool(args.include_hostname),
    )
    _print(f"支持包已生成: {path}")
    return 0


def cmd_allowlist(args: argparse.Namespace) -> int:
    from backend.services.rescue.allowlist import write_allowlist

    out = write_allowlist(Path(args.output) if args.output else None)
    _print(f"放行清单已生成: {out}")
    return 0


# ============================================================
# security
# ============================================================


def cmd_security(args: argparse.Namespace) -> int:
    from backend.services.rescue import security_software as ss

    action = args.action
    if action == "detect":
        products = ss.detect_products()
        if args.as_json:
            _print(json.dumps([p.__dict__ for p in products], ensure_ascii=False, indent=2))
            return 0
        if not products:
            _print("未检测到已知遗留管控软件")
            return 0
        for p in products:
            _print(f"  - {p.kind}: {p.target} ({p.status}) — {p.name}")
        return 0

    if action == "stop":
        if not args.target:
            _print("错误: stop 需要 --target（服务名或进程名）")
            return 2
        if not _confirm(f"停止 {args.target}？", assume_yes=args.yes):
            return 2
        if args.kind == "process" or args.target.lower().endswith(".exe"):
            result = ss.end_process(args.target, confirm=True)
        else:
            result = ss.stop_service(args.target, confirm=True)
        _print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1

    if action == "disable":
        if not args.target:
            _print("错误: disable 需要 --target（服务名）")
            return 2
        if not _confirm(
            f"禁用服务 {args.target}（需要管理员权限，可 restore 恢复）？", assume_yes=args.yes
        ):
            return 2
        result = ss.disable_service(args.target, confirm=True)
        _print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1

    if action == "restore":
        results = ss.restore_all()
        if not results:
            _print("没有可恢复的服务备份")
            return 0
        for r in results:
            _print(json.dumps(dataclasses.asdict(r), ensure_ascii=False))
        return 0 if all(r.ok for r in results) else 1

    if action == "plan":
        _print(json.dumps(ss.plan_bypass(), ensure_ascii=False, indent=2))
        return 0

    _print(f"错误: 未知 security 动作: {action}")
    return 2


# ============================================================
# safe-mode
# ============================================================


def cmd_safe_mode(args: argparse.Namespace) -> int:
    from backend.services.rescue import compat_profile as cp

    if args.action == "status":
        profile = cp.read_profile()
        _print(json.dumps(profile, ensure_ascii=False, indent=2))
        return 0
    if args.action == "off":
        cp.set_level(0, reason="user: off")
        _print("已恢复 L0（正常模式）")
        return 0
    if args.action == "set":
        if args.level is None:
            _print("错误: set 需要 0/1/2/3")
            return 2
        profile = cp.set_level(args.level, reason="user: manual")
        _print(f"已设置兼容档位 L{profile['level']}")
        return 0
    _print(f"错误: 未知 safe-mode 动作: {args.action}")
    return 2


# ============================================================
# REPL
# ============================================================


def _repl_config() -> None:
    from backend.services.rescue import config_wizard as cw

    while True:
        _print()
        _print("配置模型端点")
        _print("  [1] 列出端点")
        _print("  [2] 新增端点")
        _print("  [3] 修改端点")
        _print("  [4] 测试连接")
        _print("  [5] 设为当前聊天模型")
        _print("  [6] 导入配置包")
        _print("  [7] 导出配置包")
        _print("  [q] 返回")
        choice = _ask("请选择")
        if choice in ("q", ""):
            return
        try:
            if choice == "1":
                _print_endpoints(cw.list_endpoints())
            elif choice == "2":
                base_url = _ask("Base URL（如 http://10.0.0.5:8000/v1）")
                api_key = _ask_secret("API Key（可留空）")
                model = _ask("模型 ID（可留空）")
                name = _ask("端点名称（可留空）")
                result = cw.save_endpoint(
                    {"baseUrl": base_url, "apiKey": api_key, "modelId": model, "name": name},
                    mode="create",
                )
                _print(f"已创建: {result['endpoint']['id']}")
            elif choice == "3":
                endpoints = cw.list_endpoints()
                _print_endpoints(endpoints)
                ep_id = _ask("要修改的端点 ID")
                if not ep_id:
                    continue
                endpoint: Dict[str, Any] = {"id": ep_id}
                base_url = _ask("新 Base URL（留空不变）")
                if base_url:
                    endpoint["baseUrl"] = base_url
                api_key = _ask_secret("新 API Key（留空不变）")
                if api_key:
                    endpoint["apiKey"] = api_key
                model = _ask("新模型 ID（留空不变）")
                if model:
                    endpoint["modelId"] = model
                cw.save_endpoint(endpoint, mode="update")
                _print("已更新")
            elif choice == "4":
                endpoints = cw.list_endpoints()
                _print_endpoints(endpoints)
                ep_id = _ask("要测试的端点 ID")
                if not ep_id:
                    continue
                ep = cw.get_endpoint(ep_id)
                if ep is None:
                    _print("端点不存在")
                    continue
                outcome = cw.probe_connectivity(ep, timeout_s=5.0)
                _print(f"结果: {outcome['category']} — {outcome['message']}")
                if outcome.get("models"):
                    _print("模型: " + ", ".join(str(m) for m in outcome["models"][:20]))
            elif choice == "5":
                endpoints = cw.list_endpoints()
                _print_endpoints(endpoints)
                ep_id = _ask("端点 ID")
                model = _ask("模型 ID")
                if ep_id and model:
                    cw.save_model_selection("chatModel", ep_id, model)
                    _print("已设为当前聊天模型")
            elif choice == "6":
                path = _ask("配置包路径")
                if path:
                    summary = cw.import_bundle(Path(path), include_secrets=False)
                    _print(
                        f"导入完成: 端点 {summary['endpoints_imported']} 个, "
                        f"模型选择 {summary['model_selections_imported']} 个"
                    )
            elif choice == "7":
                path = _ask("导出路径", "sage-config-bundle.json")
                cw.export_bundle(Path(path), include_secrets=False)
                _print(f"已导出（脱敏）: {path}")
        except Exception as exc:  # noqa: BLE001 — REPL 顶层：错误不退出菜单
            _print(f"错误: {exc}")


def _repl_repair() -> None:
    from backend.services.rescue import repair

    while True:
        _print()
        _print("修复启动问题")
        _print("  [1] 清理 Chromium 缓存")
        _print("  [2] 重置窗口位置")
        _print("  [3] 截断超大日志")
        _print("  [4] 清理 8765 端口孤儿进程")
        _print("  [5] 备份并重置端点配置")
        _print("  [6] 数据库完整性检查")
        _print("  [q] 返回")
        choice = _ask("请选择")
        if choice in ("q", ""):
            return
        try:
            if choice == "1":
                if _confirm("清理缓存？"):
                    _print(json.dumps(repair.clear_caches(confirm=True), ensure_ascii=False, indent=2))
            elif choice == "2":
                if _confirm("重置窗口位置？"):
                    _print(json.dumps(repair.reset_window_state(confirm=True), ensure_ascii=False, indent=2))
            elif choice == "3":
                _print(json.dumps(repair.truncate_logs(), ensure_ascii=False, indent=2))
            elif choice == "4":
                if _confirm("结束占用 8765 的进程？"):
                    _print(json.dumps(repair.kill_orphan_backend(confirm=True), ensure_ascii=False, indent=2))
            elif choice == "5":
                if _confirm("重置端点配置（会丢失全部端点）？"):
                    _print(json.dumps(repair.reset_config(confirm=True), ensure_ascii=False, indent=2))
            elif choice == "6":
                _print(json.dumps(repair.check_db_integrity(), ensure_ascii=False, indent=2))
        except Exception as exc:
            _print(f"错误: {exc}")


def _repl_security() -> None:
    from backend.services.rescue import security_software as ss

    while True:
        _print()
        _print("处置遗留管控软件")
        _print("  [1] 检测已知组件")
        _print("  [2] 临时结束进程")
        _print("  [3] 停止服务")
        _print("  [4] 禁用服务（需管理员）")
        _print("  [5] 恢复服务（从备份）")
        _print("  [6] 查看绕过建议")
        _print("  [q] 返回")
        choice = _ask("请选择")
        if choice in ("q", ""):
            return
        try:
            if choice == "1":
                products = ss.detect_products()
                if not products:
                    _print("未检测到已知组件")
                for p in products:
                    _print(f"  - {p.kind}: {p.target} ({p.status}) — {p.name}")
            elif choice == "2":
                target = _ask("进程名（如 VrvProtect.exe）")
                if target and _confirm(f"结束 {target}？"):
                    r = ss.end_process(target, confirm=True)
                    _print(json.dumps(dataclasses.asdict(r), ensure_ascii=False, indent=2))
            elif choice == "3":
                target = _ask("服务名（如 VrvProtect）")
                if target and _confirm(f"停止服务 {target}？"):
                    r = ss.stop_service(target, confirm=True)
                    _print(json.dumps(dataclasses.asdict(r), ensure_ascii=False, indent=2))
            elif choice == "4":
                target = _ask("服务名")
                if target and _confirm(f"禁用服务 {target}？需要管理员权限，可用 [5] 恢复"):
                    r = ss.disable_service(target, confirm=True)
                    _print(json.dumps(dataclasses.asdict(r), ensure_ascii=False, indent=2))
            elif choice == "5":
                results = ss.restore_all()
                if not results:
                    _print("没有可恢复的服务备份")
                for r in results:
                    _print(json.dumps(dataclasses.asdict(r), ensure_ascii=False))
            elif choice == "6":
                _print(json.dumps(ss.plan_bypass(), ensure_ascii=False, indent=2))
        except Exception as exc:
            _print(f"错误: {exc}")


def _repl_crash_history() -> None:
    from backend.services.rescue.paths import crash_journal_path

    path = crash_journal_path()
    if not path.is_file():
        _print("尚无崩溃记录")
        return
    _print(f"崩溃记录: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-50:]
        for line in lines:
            _print(line)
    except Exception as exc:
        _print(f"读取失败: {exc}")


def repl() -> int:
    _banner()
    while True:
        _print()
        _print("[1] 一键体检")
        _print("[2] 配置模型端点")
        _print("[3] 修复启动问题")
        _print("[4] 生成诊断包（发给 IT/支持）")
        _print("[5] 生成管控软件放行清单")
        _print("[6] 处置遗留管控软件")
        _print("[7] 查看崩溃记录")
        _print("[q] 退出")
        choice = _ask("请选择")
        if choice in ("q", ""):
            _print("再见。")
            return 0
        try:
            if choice == "1":
                run_diagnostics()
            elif choice == "2":
                _repl_config()
            elif choice == "3":
                _repl_repair()
            elif choice == "4":
                cmd_report(argparse.Namespace(include_crashdumps=False, include_hostname=False))
            elif choice == "5":
                cmd_allowlist(argparse.Namespace(output=None))
            elif choice == "6":
                _repl_security()
            elif choice == "7":
                _repl_crash_history()
        except Exception as exc:
            _print(f"错误: {exc}")


# ============================================================
# CLI 解析
# ============================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backend.cli.rescue",
        description="Sage 修复工具（前端不可用时的独立诊断/配置/修复入口）",
    )
    # --yes 放在子命令层级（如 `rescue repair cache --yes`），避免必须在
    # 子命令之前传递的困惑。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--yes", action="store_true", help="跳过交互确认（仅限脚本/对话框调用）")
    sub = parser.add_subparsers(dest="command")

    p_diag = sub.add_parser("diag", parents=[common], help="运行全部环境检查")
    p_diag.add_argument("--json", action="store_true", dest="as_json")

    p_config = sub.add_parser("config", parents=[common], help="配置端点/模型")
    p_config.add_argument(
        "action", choices=["list", "add", "update", "remove", "test", "use", "import", "export"]
    )
    p_config.add_argument("--id", dest="endpoint_id", default=None)
    p_config.add_argument("--base-url", default=None)
    p_config.add_argument("--api-key", default=None)
    p_config.add_argument("--model", default=None)
    p_config.add_argument("--name", default=None)
    p_config.add_argument(
        "--protocol",
        default="openai-compatible",
        choices=["openai-compatible", "anthropic", "gemini", "ollama"],
    )
    p_config.add_argument(
        "--task",
        default="chatModel",
        choices=["chatModel", "visionModel", "embeddingModel", "ttsModel", "asrModel", "imageGenModel"],
    )
    p_config.add_argument("--file", default=None)
    p_config.add_argument("--include-secrets", action="store_true")
    p_config.add_argument("--no-backup", action="store_true")
    p_config.add_argument("--timeout", type=float, default=5.0)
    p_config.add_argument("--json", action="store_true", dest="as_json")

    p_repair = sub.add_parser("repair", parents=[common], help="安全修复动作")
    p_repair.add_argument("action", choices=["cache", "window", "logs", "port", "config", "db"])
    p_repair.add_argument("--max-mb", type=int, default=10)
    p_repair.add_argument("--port", type=int, default=None)

    p_report = sub.add_parser("report", parents=[common], help="生成支持包")
    p_report.add_argument("--include-crashdumps", action="store_true")
    p_report.add_argument("--include-hostname", action="store_true")

    p_allow = sub.add_parser("allowlist", parents=[common], help="生成管控软件放行清单")
    p_allow.add_argument("--output", default=None)

    p_sec = sub.add_parser("security", parents=[common], help="遗留管控软件处置")
    p_sec.add_argument("action", choices=["detect", "stop", "disable", "restore", "plan"])
    p_sec.add_argument("--target", default=None)
    p_sec.add_argument("--kind", choices=["service", "process"], default="service")
    p_sec.add_argument("--json", action="store_true", dest="as_json")

    p_safe = sub.add_parser("safe-mode", parents=[common], help="兼容档位")
    p_safe.add_argument("action", choices=["status", "set", "off"])
    p_safe.add_argument("level", nargs="?", type=int, default=None)

    sub.add_parser("shell", parents=[common], help="交互式 REPL（默认）")
    return parser


def main(argv: Optional[list] = None) -> int:
    _configure_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "shell"
    try:
        if command == "shell":
            return repl()
        if command == "diag":
            return cmd_diag(args)
        if command == "config":
            return cmd_config(args)
        if command == "repair":
            return cmd_repair(args)
        if command == "report":
            return cmd_report(args)
        if command == "allowlist":
            return cmd_allowlist(args)
        if command == "security":
            return cmd_security(args)
        if command == "safe-mode":
            return cmd_safe_mode(args)
    except Exception as exc:  # noqa: BLE001 — CLI 顶层兜底
        _print(f"错误: {exc}")
        return 2
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
