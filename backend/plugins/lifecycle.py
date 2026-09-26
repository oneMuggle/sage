"""
Plugin lifecycle management.

This module provides the PluginLifecycleManager for managing plugin states:
install, enable, disable, uninstall, and restore.

Plugin states are persisted to SQLite for reliability across restarts.

Author: Claude
Date: 2026-09-26
"""

from __future__ import annotations

import logging
import sqlite3
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field

from backend.plugins.manifest import PluginManifest, PluginType

logger = logging.getLogger(__name__)


class PluginStatus(str, Enum):
    """Plugin installation and activation status."""

    INSTALLED = "installed"  # 已安装但未启用
    ENABLED = "enabled"  # 已启用（可用）
    DISABLED = "disabled"  # 已禁用（用户手动）
    UNINSTALLED = "uninstalled"  # 已卸载


class PluginRecord(BaseModel):
    """Plugin record stored in database."""

    name: str = Field(..., description="插件唯一标识符")
    version: str = Field(..., description="当前安装版本")
    status: PluginStatus = Field(default=PluginStatus.INSTALLED, description="插件状态")
    plugin_type: PluginType = Field(default=PluginType.PERSONAL, description="插件类型")
    install_path: str = Field(..., description="插件安装路径")
    installed_at: float = Field(..., description="安装时间戳（秒）")
    enabled_at: Optional[float] = Field(default=None, description="启用时间戳")
    disabled_at: Optional[float] = Field(default=None, description="禁用时间戳")
    uninstalled_at: Optional[float] = Field(default=None, description="卸载时间戳")
    config: Dict[str, Any] = Field(default_factory=dict, description="用户配置")

    class Config:
        """Pydantic v1 compatibility."""

        use_enum_values = True


class PluginLifecycleError(Exception):
    """Base exception for plugin lifecycle errors."""

    pass


class PluginNotFoundError(PluginLifecycleError):
    """Raised when plugin is not found."""

    pass


class PluginAlreadyExistsError(PluginLifecycleError):
    """Raised when plugin already exists."""

    pass


class PluginStateError(PluginLifecycleError):
    """Raised when state transition is invalid."""

    pass


class PluginLifecycleManager:
    """
    Manage plugin lifecycle: install, enable, disable, uninstall, restore.

    Plugin states are persisted to SQLite database for reliability.

    Usage:
        manager = PluginLifecycleManager()
        manager.install(manifest, "/path/to/plugin")
        manager.enable("my-plugin")
        manager.disable("my-plugin")
        manager.uninstall("my-plugin")
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """
        Initialize lifecycle manager.

        Args:
            db_path: Optional custom database path. If None, uses default Sage database.
        """
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection (lazy initialization)."""
        if self._conn is not None:
            return self._conn

        if self._db_path is not None:
            # Custom database path
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
        else:
            # Use Sage's default database
            from backend.data.database import get_database

            self._conn = get_database().get_connection()

        self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self) -> None:
        """Ensure plugins table exists."""
        conn = self._get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plugins (
                name TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'installed',
                plugin_type TEXT NOT NULL DEFAULT 'personal',
                install_path TEXT NOT NULL,
                installed_at REAL NOT NULL,
                enabled_at REAL,
                disabled_at REAL,
                uninstalled_at REAL,
                config TEXT DEFAULT '{}'
            )
            """
        )
        conn.commit()

    def install(
        self, manifest: PluginManifest, install_path: Union[str, Path]
    ) -> PluginRecord:
        """
        Install a plugin.

        Args:
            manifest: Plugin manifest
            install_path: Path to plugin directory

        Returns:
            PluginRecord for the installed plugin

        Raises:
            PluginAlreadyExistsError: If plugin already installed
        """
        if self._plugin_exists(manifest.name):
            raise PluginAlreadyExistsError(f"插件已安装: {manifest.name}")

        conn = self._get_connection()
        now = time.time()

        try:
            conn.execute(
                """
                INSERT INTO plugins (
                    name, version, status, plugin_type, install_path,
                    installed_at, config
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.name,
                    manifest.version,
                    PluginStatus.INSTALLED.value,
                    manifest.type.value,
                    str(install_path),
                    now,
                    "{}",
                ),
            )
            conn.commit()

            logger.info(f"插件已安装: {manifest.name} v{manifest.version}")

            return self.get_plugin(manifest.name)

        except sqlite3.Error as e:
            logger.error(f"插件安装失败: {e}")
            raise PluginLifecycleError(f"安装失败: {e}") from e

    def enable(self, plugin_name: str) -> PluginRecord:
        """
        Enable an installed or disabled plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            Updated PluginRecord

        Raises:
            PluginNotFoundError: If plugin not found
            PluginStateError: If plugin is uninstalled
        """
        record = self.get_plugin(plugin_name)

        if record.status == PluginStatus.UNINSTALLED:
            raise PluginStateError(f"插件已卸载: {plugin_name}")

        if record.status == PluginStatus.ENABLED:
            logger.warning(f"插件已启用: {plugin_name}")
            return record

        conn = self._get_connection()
        now = time.time()

        try:
            conn.execute(
                """
                UPDATE plugins
                SET status = ?, enabled_at = ?, disabled_at = NULL
                WHERE name = ?
                """,
                (PluginStatus.ENABLED.value, now, plugin_name),
            )
            conn.commit()

            logger.info(f"插件已启用: {plugin_name}")

            return self.get_plugin(plugin_name)

        except sqlite3.Error as e:
            logger.error(f"插件启用失败: {e}")
            raise PluginLifecycleError(f"启用失败: {e}") from e

    def disable(self, plugin_name: str) -> PluginRecord:
        """
        Disable an enabled plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            Updated PluginRecord

        Raises:
            PluginNotFoundError: If plugin not found
            PluginStateError: If plugin is not enabled
        """
        record = self.get_plugin(plugin_name)

        if record.status != PluginStatus.ENABLED:
            raise PluginStateError(
                f"插件未启用，无法禁用: {plugin_name} (当前状态: {record.status})"
            )

        conn = self._get_connection()
        now = time.time()

        try:
            conn.execute(
                """
                UPDATE plugins
                SET status = ?, disabled_at = ?
                WHERE name = ?
                """,
                (PluginStatus.DISABLED.value, now, plugin_name),
            )
            conn.commit()

            logger.info(f"插件已禁用: {plugin_name}")

            return self.get_plugin(plugin_name)

        except sqlite3.Error as e:
            logger.error(f"插件禁用失败: {e}")
            raise PluginLifecycleError(f"禁用失败: {e}") from e

    def uninstall(self, plugin_name: str) -> None:
        """
        Uninstall a plugin (soft delete - marks as uninstalled).

        Args:
            plugin_name: Plugin name

        Raises:
            PluginNotFoundError: If plugin not found
        """
        record = self.get_plugin(plugin_name)

        if record.status == PluginStatus.UNINSTALLED:
            logger.warning(f"插件已卸载: {plugin_name}")
            return

        conn = self._get_connection()
        now = time.time()

        try:
            conn.execute(
                """
                UPDATE plugins
                SET status = ?, uninstalled_at = ?
                WHERE name = ?
                """,
                (PluginStatus.UNINSTALLED.value, now, plugin_name),
            )
            conn.commit()

            logger.info(f"插件已卸载: {plugin_name}")

        except sqlite3.Error as e:
            logger.error(f"插件卸载失败: {e}")
            raise PluginLifecycleError(f"卸载失败: {e}") from e

    def restore(self, plugin_name: str) -> PluginRecord:
        """
        Restore an uninstalled plugin to installed state.

        Args:
            plugin_name: Plugin name

        Returns:
            Updated PluginRecord

        Raises:
            PluginNotFoundError: If plugin not found
            PluginStateError: If plugin is not uninstalled
        """
        record = self.get_plugin(plugin_name)

        if record.status != PluginStatus.UNINSTALLED:
            raise PluginStateError(
                f"插件未卸载，无法恢复: {plugin_name} (当前状态: {record.status})"
            )

        conn = self._get_connection()
        now = time.time()

        try:
            conn.execute(
                """
                UPDATE plugins
                SET status = ?, uninstalled_at = NULL, installed_at = ?
                WHERE name = ?
                """,
                (PluginStatus.INSTALLED.value, now, plugin_name),
            )
            conn.commit()

            logger.info(f"插件已恢复: {plugin_name}")

            return self.get_plugin(plugin_name)

        except sqlite3.Error as e:
            logger.error(f"插件恢复失败: {e}")
            raise PluginLifecycleError(f"恢复失败: {e}") from e

    def get_plugin(self, plugin_name: str) -> PluginRecord:
        """
        Get plugin record by name.

        Args:
            plugin_name: Plugin name

        Returns:
            PluginRecord

        Raises:
            PluginNotFoundError: If plugin not found
        """
        conn = self._get_connection()

        try:
            row = conn.execute(
                "SELECT * FROM plugins WHERE name = ?", (plugin_name,)
            ).fetchone()

            if row is None:
                raise PluginNotFoundError(f"插件未找到: {plugin_name}")

            return self._row_to_record(row)

        except sqlite3.Error as e:
            logger.error(f"获取插件失败: {e}")
            raise PluginLifecycleError(f"获取失败: {e}") from e

    def list_plugins(
        self, status: Optional[PluginStatus] = None
    ) -> List[PluginRecord]:
        """
        List all plugins, optionally filtered by status.

        Args:
            status: Optional status filter

        Returns:
            List of PluginRecord
        """
        conn = self._get_connection()

        try:
            if status is not None:
                rows = conn.execute(
                    "SELECT * FROM plugins WHERE status = ? ORDER BY installed_at DESC",
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM plugins ORDER BY installed_at DESC"
                ).fetchall()

            return [self._row_to_record(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"列出插件失败: {e}")
            raise PluginLifecycleError(f"列出失败: {e}") from e

    def update_config(self, plugin_name: str, config: Dict[str, Any]) -> PluginRecord:
        """
        Update plugin configuration.

        Args:
            plugin_name: Plugin name
            config: New configuration

        Returns:
            Updated PluginRecord

        Raises:
            PluginNotFoundError: If plugin not found
        """
        import json

        # 验证插件存在（不存在则抛异常）
        self.get_plugin(plugin_name)

        conn = self._get_connection()

        try:
            conn.execute(
                "UPDATE plugins SET config = ? WHERE name = ?",
                (json.dumps(config), plugin_name),
            )
            conn.commit()

            logger.info(f"插件配置已更新: {plugin_name}")

            return self.get_plugin(plugin_name)

        except sqlite3.Error as e:
            logger.error(f"更新配置失败: {e}")
            raise PluginLifecycleError(f"更新失败: {e}") from e

    def _plugin_exists(self, plugin_name: str) -> bool:
        """Check if plugin exists (any status)."""
        conn = self._get_connection()

        try:
            row = conn.execute(
                "SELECT 1 FROM plugins WHERE name = ?", (plugin_name,)
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def _row_to_record(self, row: sqlite3.Row) -> PluginRecord:
        """Convert database row to PluginRecord."""
        import json

        config_str = row["config"] or "{}"
        try:
            config = json.loads(config_str)
        except json.JSONDecodeError:
            config = {}

        return PluginRecord(
            name=row["name"],
            version=row["version"],
            status=PluginStatus(row["status"]),
            plugin_type=PluginType(row["plugin_type"]),
            install_path=row["install_path"],
            installed_at=row["installed_at"],
            enabled_at=row["enabled_at"],
            disabled_at=row["disabled_at"],
            uninstalled_at=row["uninstalled_at"],
            config=config,
        )

    def close(self) -> None:
        """Close database connection (if using custom path)."""
        if self._conn is not None and self._db_path is not None:
            self._conn.close()
            self._conn = None


# Global instance (lazy initialization)
_lifecycle_manager: Optional[PluginLifecycleManager] = None


def get_lifecycle_manager() -> PluginLifecycleManager:
    """Get global lifecycle manager instance."""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = PluginLifecycleManager()
    return _lifecycle_manager
