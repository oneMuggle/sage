"""安全修复动作（M1 cache/window/logs/port/config/db 等）。

每个动作：

- 幂等（重复执行结果相同）；
- 先备份再改；
- 返回 ``ActionResult`` 供 CLI / 对话框统一呈现；
- 不删除用户数据（sessions/wiki/memories）除非显式确认。
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.rescue.paths import backups_dir, resolve_db_path, resolve_user_data_dir

logger = logging.getLogger(__name__)


class RepairError(Exception):
    """修复动作失败。"""


def _record_action(user_data_dir: Path, entry: Dict[str, Any]) -> None:
    """追加一条动作审计到 ``diagnostics/rescue-actions.jsonl``。"""
    from backend.services.rescue.paths import rescue_actions_log

    path = rescue_actions_log(user_data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **entry}
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("rescue: 写 rescue-actions.jsonl 失败", exc_info=True)


def clear_caches(*, user_data_dir: Optional[Path] = None, confirm: bool = False) -> Dict[str, Any]:
    """清理 Chromium GPU/代码/着色器缓存目录。

    目标子目录：``Cache``、``Code Cache``、``GPUCache``、``ShaderCache``、``DawnCache``。
    不触碰 ``Local Storage`` / ``IndexedDB``（这些是用户数据）。
    """
    base = user_data_dir or resolve_user_data_dir()
    targets = [base / sub for sub in ("Cache", "Code Cache", "GPUCache", "ShaderCache", "DawnCache")]
    if not confirm:
        return {"action": "clear_caches", "dry_run": True, "would_clear": [str(t) for t in targets if t.exists()]}
    freed = 0
    cleared: List[str] = []
    for t in targets:
        if not t.exists():
            continue
        try:
            size = sum(f.stat().st_size for f in t.rglob("*") if f.is_file())
            shutil.rmtree(t)
            freed += size
            cleared.append(str(t))
        except Exception as exc:
            logger.warning("clear_caches: 清理 %s 失败: %s", t, exc)
    _record_action(base, {"action": "clear_caches", "cleared": cleared, "freed_bytes": freed})
    return {"action": "clear_caches", "cleared": cleared, "freed_bytes": freed}


def reset_window_state(*, user_data_dir: Optional[Path] = None, confirm: bool = False) -> Dict[str, Any]:
    """清除窗口位置/大小（让应用下次用默认位置启动）。

    影响：``<userData>/window-state.json`` 类状态文件。
    """
    base = user_data_dir or resolve_user_data_dir()
    target = base / "window-state.json"
    if not confirm:
        return {"action": "reset_window_state", "dry_run": not target.exists(), "target": str(target)}
    removed = False
    if target.exists():
        try:
            target.unlink()
            removed = True
        except Exception as exc:
            logger.warning("reset_window_state: 删除失败: %s", exc)
    _record_action(base, {"action": "reset_window_state", "removed": removed, "target": str(target)})
    return {"action": "reset_window_state", "removed": removed}


def truncate_logs(*, user_data_dir: Optional[Path] = None, max_mb: int = 10) -> Dict[str, Any]:
    """把超大 NDJSON 日志截断到最近 N MB。非破坏性：备份原文件再替换。"""
    base = user_data_dir or resolve_user_data_dir()
    logs_dir = base / "logs"
    if not logs_dir.is_dir():
        return {"action": "truncate_logs", "scanned": 0, "truncated": 0}
    scanned = 0
    truncated = 0
    backup_root = backups_dir(base) / "logs"
    backup_root.mkdir(parents=True, exist_ok=True)
    for f in logs_dir.glob("*.ndjson"):
        scanned += 1
        size = f.stat().st_size
        if size <= max_mb * 1024 * 1024:
            continue
        # 备份原文件
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
            shutil.copy2(f, backup_root / f"{f.stem}-{stamp}{f.suffix}")
            with f.open("rb") as src:
                src.seek(-(max_mb * 1024 * 1024), 2)
                tail = src.read()
            with f.open("wb") as dst:
                dst.write(tail)
            truncated += 1
        except Exception as exc:
            logger.warning("truncate_logs: 处理 %s 失败: %s", f, exc)
    _record_action(base, {"action": "truncate_logs", "scanned": scanned, "truncated": truncated})
    return {"action": "truncate_logs", "scanned": scanned, "truncated": truncated}


def kill_orphan_backend(
    *, port: Optional[int] = None, confirm: bool = False
) -> Dict[str, Any]:
    """杀死占用指定端口的孤儿 Sage backend 进程（Win32 only）。

    - 端口默认读 ``PYTHON_BACKEND_PORT``，回退 8765；
    - 杀之前校验命令行包含 ``backend.main`` 或 python，避免误杀其他程序。
    """
    import os
    import platform as _platform

    if _platform.system() != "Windows":
        return {"action": "kill_orphan_backend", "unsupported": True}
    import subprocess

    if port is None:
        try:
            port = int(os.environ.get("PYTHON_BACKEND_PORT", "8765"))
        except ValueError:
            port = 8765

    # netstat -ano 取 LISTENING 端口
    try:
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except Exception as exc:
        return {"action": "kill_orphan_backend", "error": str(exc)}
    pids = []
    for line in (proc.stdout or "").splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                try:
                    pids.append(int(parts[-1]))
                except ValueError:
                    continue

    verified = []
    for pid in pids:
        commandline = ""
        try:
            p = subprocess.run(
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            lines = [
                line
                for line in (p.stdout or "").splitlines()
                if line.strip() and not line.startswith("Node,")
            ]
            commandline = lines[-1].split(",", 1)[-1].strip() if lines else ""
        except Exception:
            commandline = ""
        if "backend.main" in commandline or "python" in commandline.lower():
            verified.append(pid)

    if not verified:
        return {
            "action": "kill_orphan_backend",
            "killed": [],
            "note": f"端口 {port} 无已确认的 Sage backend 进程（不会误杀其他程序）",
        }
    if not confirm:
        return {"action": "kill_orphan_backend", "dry_run": True, "would_kill": verified}
    killed = []
    for pid in verified:
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                timeout=10,
                check=False,
            )
            killed.append(pid)
        except Exception as exc:
            logger.warning("kill_orphan_backend: pid %s 失败: %s", pid, exc)
    return {"action": "kill_orphan_backend", "killed": killed}


def backup_config(*, user_data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """备份 ``sage.db`` 到 ``backups/rescue-config-<ts>.db``。"""
    from backend.services.backup_service import create_backup

    db_path = (user_data_dir / "sage.db") if user_data_dir is not None else resolve_db_path()
    if not db_path.exists():
        return {"action": "backup_config", "skipped": "no_db"}
    backup = create_backup("rescue-config", db_path=str(db_path))
    return {"action": "backup_config", "backup": backup}


def check_db_integrity(*, user_data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """DB 完整性检查：``PRAGMA quick_check`` + schema 版本。"""
    import sqlite3

    db_path = (user_data_dir / "sage.db") if user_data_dir is not None else resolve_db_path()
    if not db_path.exists():
        return {"ok": False, "missing": True, "message": "DB 文件不存在"}
    try:
        # 优先普通连接 + query_only（WAL 库在 mode=ro 下无写权限回放可能报错）；
        # 只读文件系统时回退到正确的 file URI（路径已转义）。
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
        return {"ok": ok, "quick_check": [r[0] for r in rows], "schema_version": schema}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def reset_config(*, confirm: bool = False, user_data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """备份并重置 app_settings（保留 schema_version）。

    高危：重置后所有端点/模型选择丢失，必须 confirm。
    """
    from backend.data.database import Database
    from backend.data.settings_repo import SettingsRepository

    base = user_data_dir or resolve_user_data_dir()
    if not confirm:
        return {"action": "reset_config", "dry_run": True}
    db_path_obj = (user_data_dir / "sage.db") if user_data_dir is not None else resolve_db_path()
    db_path = str(db_path_obj)
    db = Database(db_path=db_path)
    try:
        backup = backup_config(user_data_dir=base)
        repo = SettingsRepository(db)
        repo.set_json("app_settings", {"version": 1, "endpoints": [], "modelSelections": {}})
        _record_action(base, {"action": "reset_config", "backup": backup})
        return {"action": "reset_config", "ok": True, "backup": backup}
    finally:
        db.close()
