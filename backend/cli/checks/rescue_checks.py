"""救援工具新增的 doctor 检查项（6 项）。

- ``db_integrity`` —— SQLite ``PRAGMA quick_check`` + schema 版本
- ``endpoint_reachability`` —— 端点连通性（TCP + HTTP，分类报错）
- ``crash_history`` —— 读 ``crash-journal.jsonl`` 统计最近 7 天崩溃
- ``security_software_check`` —— 已知遗留管控软件识别
- ``port_ownership`` —— 8765 监听者 PID / 命令行
- ``data_dir_paths`` —— userData / logs / backups 目录可写与大小
"""
from __future__ import annotations

import platform
import subprocess
import time

from backend.cli.doctor import CheckResult, Severity, register
from backend.services.rescue.paths import (
    crash_journal_path,
    resolve_db_path,
    resolve_user_data_dir,
)


@register
class DbIntegrityCheck:
    name = "db_integrity"
    description = "SQLite 数据库完整性（quick_check + schema_version）"

    def run(self) -> CheckResult:
        import sqlite3

        db_path = resolve_db_path()
        if not db_path.exists():
            return CheckResult(self.name, Severity.INFO, f"DB 不存在: {db_path}")
        try:
            try:
                conn = sqlite3.connect(str(db_path), timeout=2)
                conn.execute("PRAGMA query_only = ON")
            except sqlite3.OperationalError:
                uri = f"{db_path.resolve().as_uri()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=2)
            rows = conn.execute("PRAGMA quick_check").fetchall()
            schema = None
            try:
                row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
                if row:
                    schema = row[0]
            except sqlite3.OperationalError:
                pass
            conn.close()
            ok = all(r[0] == "ok" for r in rows)
            if ok:
                return CheckResult(
                    self.name,
                    Severity.INFO,
                    f"DB 完整性通过 (schema_version={schema})",
                )
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"DB quick_check 失败: {[r[0] for r in rows]}",
                "运行 `python -m backend.cli.rescue repair db` 或重装",
            )
        except Exception as exc:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"DB 无法打开: {exc}",
                "检查 userData 目录权限",
            )


@register
class EndpointReachabilityCheck:
    name = "endpoint_reachability"
    description = "LLM 端点连通性（TCP + HTTP，分类报错）"

    def run(self) -> CheckResult:
        from backend.data.settings_repo import SettingsRepository

        try:
            repo = SettingsRepository()
            settings = repo.get_json("app_settings") or {}
            endpoints = settings.get("endpoints") or []
        except Exception as exc:
            return CheckResult(self.name, Severity.WARN, f"读取配置失败: {exc}")
        if not endpoints:
            return CheckResult(self.name, Severity.INFO, "未配置任何端点")
        results = []
        for ep in endpoints:
            if not isinstance(ep, dict):
                continue
            name = ep.get("name") or ep.get("id") or "<unnamed>"
            base_url = ep.get("baseUrl") or ""
            if not base_url:
                results.append(f"{name}: 无 baseUrl")
                continue
            try:
                from backend.services.rescue.config_wizard import probe_connectivity

                outcome = probe_connectivity(ep, timeout_s=3.0)
                results.append(f"{name}: {outcome['category']}")
            except Exception as exc:
                results.append(f"{name}: 探测失败 {exc}")
        unreachable = [r for r in results if ": ok" not in r]
        if not unreachable:
            return CheckResult(self.name, Severity.INFO, "所有端点可达: " + "; ".join(results))
        return CheckResult(
            self.name,
            Severity.WARN,
            "部分端点不可达: " + "; ".join(results),
            "运行 `python -m backend.cli.rescue config test` 查看详情",
        )


@register
class CrashHistoryCheck:
    name = "crash_history"
    description = "最近 7 天崩溃事件统计（基于 crash-journal.jsonl）"

    def run(self) -> CheckResult:
        path = crash_journal_path()
        if not path.is_file():
            return CheckResult(self.name, Severity.INFO, "尚无崩溃记录")
        import json

        cutoff = time.time() - 7 * 86400
        counts = {}
        latest = None
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    ts = rec.get("ts")
                    if not ts:
                        continue
                    try:
                        # ISO 8601 UTC 解析（带 Z 后缀）
                        from datetime import datetime, timezone

                        t = (
                            datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
                            .replace(tzinfo=timezone.utc)  # noqa: UP017 — Py3.8 compat
                            .timestamp()
                        )
                    except Exception:
                        continue
                    if t < cutoff:
                        continue
                    event = rec.get("event", "unknown")
                    counts[event] = counts.get(event, 0) + 1
                    latest = ts
        except Exception as exc:
            return CheckResult(self.name, Severity.WARN, f"读 journal 失败: {exc}")
        if not counts:
            return CheckResult(self.name, Severity.INFO, "最近 7 天无崩溃")
        summary = ", ".join(f"{k}={v}" for k, v in counts.items())
        total = sum(counts.values())
        severity = Severity.CRITICAL if total >= 3 else Severity.WARN
        return CheckResult(
            self.name,
            severity,
            f"最近 7 天崩溃 {total} 次: {summary} (最新 {latest})",
            "运行 `python -m backend.cli.rescue report` 生成支持包",
        )


@register
class SecuritySoftwareCheck:
    name = "security_software"
    description = "已知遗留管控软件/安全产品识别（仅信息）"

    def run(self) -> CheckResult:
        if platform.system() != "Windows":
            return CheckResult(self.name, Severity.INFO, f"平台 {platform.system()}，跳过")
        from backend.services.rescue.security_software import detect_products

        try:
            products = detect_products()
        except Exception as exc:
            return CheckResult(self.name, Severity.WARN, f"检测失败: {exc}")
        if not products:
            return CheckResult(self.name, Severity.INFO, "未检测到已知遗留管控软件")
        summary = "; ".join(f"{p.kind}:{p.target}({p.status})" for p in products)
        return CheckResult(
            self.name,
            Severity.INFO,
            f"检测到 {len(products)} 个组件: {summary}",
            "运行 `python -m backend.cli.rescue security` 查看详情",
        )


@register
class PortOwnershipCheck:
    name = "port_ownership"
    description = "8765 端口监听者 PID / 命令行（识别孤儿 backend）"

    def run(self) -> CheckResult:
        if platform.system() != "Windows":
            return CheckResult(self.name, Severity.INFO, f"平台 {platform.system()}，跳过")
        try:
            proc = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
            )
        except Exception as exc:
            return CheckResult(self.name, Severity.WARN, f"netstat 失败: {exc}")
        pids = []
        for line in (proc.stdout or "").splitlines():
            if ":8765" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    try:
                        pids.append(int(parts[-1]))
                    except ValueError:
                        continue
        if not pids:
            return CheckResult(self.name, Severity.INFO, "8765 端口空闲")
        # 尝试查命令行
        owners = []
        for pid in pids:
            try:
                p2 = subprocess.run(
                    [
                        "wmic",
                        "process",
                        "where",
                        f"ProcessId={pid}",
                        "get",
                        "CommandLine",
                        "/format:csv",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
                )
                lines = [
                    line_text
                    for line_text in (p2.stdout or "").splitlines()
                    if line_text.strip() and not line_text.startswith("Node,")
                ]
                cmd = lines[-1].split(",", 1)[-1].strip() if lines else "<unknown>"
                owners.append(f"{pid}: {cmd[:80]}")
            except Exception:
                owners.append(f"{pid}: <unknown>")
        return CheckResult(
            self.name,
            Severity.INFO if len(owners) == 1 else Severity.WARN,
            "8765 监听者: " + "; ".join(owners),
            "若为孤儿 backend，运行 `python -m backend.cli.rescue repair port` 清理",
        )


@register
class DataDirPathsCheck:
    name = "data_dir_paths"
    description = "userData / logs / backups 目录可写与大小"

    def run(self) -> CheckResult:
        import tempfile

        user_data = resolve_user_data_dir()
        issues = []
        for sub in (".", "logs", "diagnostics", "backups"):
            path = user_data / sub
            if not path.exists():
                continue
            try:
                with tempfile.NamedTemporaryFile(
                    dir=str(path), prefix="sage_doctor_", suffix=".tmp"
                ):
                    pass
            except OSError:
                issues.append(f"{sub}: 不可写")
        if issues:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                "目录权限异常: " + "; ".join(issues),
                "检查 userData 目录权限",
            )
        # 不递归扫描 userData 体积：在真实机器上可能包含大量会话/日志，
        # doctor 应保持秒级；体积信息交给 rescue report 按需统计。
        return CheckResult(
            self.name,
            Severity.INFO,
            f"userData 目录可写: {user_data}",
        )
