"""路径解析（与 ``electron/userDataPaths.ts`` 保持同语义）。

CLI 入口在启动时设置 ``SAGE_USER_DATA_DIR`` / ``SAGE_DB_PATH``。本模块只在
CLI / 救援工具内使用，优先使用环境变量覆盖；否则按平台默认回落到
``Path.home() / '.sage'``（非打包模式）。打包模式的路径由启动器脚本注入，
因此本模块对打包模式无分支 —— 启动器必须提前设置好环境变量。

所有路径函数接受可选 ``environ`` 便于测试。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Optional


def resolve_user_data_dir(environ: Optional[Mapping[str, str]] = None) -> Path:
    """解析 Sage 用户数据目录（与 ``electron/userDataPaths.ts`` 对齐）。

    优先级：

    1. ``SAGE_USER_DATA_DIR`` 环境变量；
    2. 打包模式（``SAGE_IS_PACKAGED=1``）：
       - Windows: ``%APPDATA%\\Sage``
       - macOS: ``~/Library/Application Support/Sage``
       - Linux: ``~/.config/sage``
    3. dev 模式：``<cwd>/data``（与 ``Database()`` 默认路径一致）。
    """
    env: Mapping[str, str] = environ if environ is not None else os.environ
    override = env.get("SAGE_USER_DATA_DIR")
    if override:
        return Path(override)
    if env.get("SAGE_IS_PACKAGED") == "1":
        if sys.platform.startswith("win"):
            appdata = env.get("APPDATA")
            if appdata:
                return Path(appdata) / "Sage"
            return Path.home() / "AppData" / "Roaming" / "Sage"
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Sage"
        return Path.home() / ".config" / "sage"
    return Path.cwd() / "data"


def resolve_db_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """解析 SQLite 数据库路径。

    优先级：

    1. ``SAGE_DB_PATH`` 环境变量；
    2. ``resolve_user_data_dir() / 'sage.db'``。
    """
    env: Mapping[str, str] = environ if environ is not None else os.environ
    override = env.get("SAGE_DB_PATH")
    if override:
        return Path(override)
    return resolve_user_data_dir(env) / "sage.db"


def diagnostics_dir(user_data_dir: Optional[Path] = None) -> Path:
    """``<user_data_dir>/diagnostics`` 子目录。"""
    base = user_data_dir or resolve_user_data_dir()
    return base / "diagnostics"


def backups_dir(user_data_dir: Optional[Path] = None) -> Path:
    """``<user_data_dir>/backups`` 子目录（与 ``backup_service`` 一致）。"""
    base = user_data_dir or resolve_user_data_dir()
    return base / "backups"


def compat_profile_path(user_data_dir: Optional[Path] = None) -> Path:
    """``<user_data_dir>/diagnostics/compat.json`` 兼容档位文件。"""
    return diagnostics_dir(user_data_dir) / "compat.json"


def last_run_path(user_data_dir: Optional[Path] = None) -> Path:
    """``<user_data_dir>/diagnostics/last-run.json`` 启动时间线/运行状态。"""
    return diagnostics_dir(user_data_dir) / "last-run.json"


def crash_journal_path(user_data_dir: Optional[Path] = None) -> Path:
    """``<user_data_dir>/diagnostics/crash-journal.jsonl`` 崩溃事件日志。"""
    return diagnostics_dir(user_data_dir) / "crash-journal.jsonl"


def rescue_actions_log(user_data_dir: Optional[Path] = None) -> Path:
    """``<user_data_dir>/diagnostics/rescue-actions.jsonl`` 处置动作审计。"""
    return diagnostics_dir(user_data_dir) / "rescue-actions.jsonl"


def security_backups_dir(user_data_dir: Optional[Path] = None) -> Path:
    """``<backups_dir>/security`` 子目录（管控软件处置前的状态备份）。"""
    return backups_dir(user_data_dir) / "security"
