"""远程工作区持久化：``$SAGE_USER_DATA_DIR/remote_workspaces.json``。

- 原子写（temp + ``os.replace``）；文件损坏时**不覆盖**，抛错交给调用方；
- token = 256 bit 随机 hex，只经 :meth:`WorkspaceStore.connection_token` 取出，
  :meth:`public_view` 永不包含 token；
- 落盘为 ``token_enc``（SecretBox：DPAPI / keychain / secret-tool；无后端时诚实降级），
  内存保持明文用于常量时间比对；旧明文 ``token`` 加载后立即迁移；解密失败则重置
  token、停用工作区并标记 ``token_reset``（M5a）；
- 创建时对 root 做 realpath，拒绝磁盘根与用户主目录（LocalBridge main.cjs 同款）。
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

PERMISSION_KEYS = ("read", "write", "shell")
APPROVAL_MODES = ("auto", "ask")

logger = logging.getLogger(__name__)

_FILE_NAME = "remote_workspaces.json"


class StoreError(ValueError):
    """用户可读的配置错误。"""


def default_store_path() -> str:
    base = os.environ.get("SAGE_USER_DATA_DIR") or os.path.join("backend", "data")
    return os.path.join(base, _FILE_NAME)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class WorkspaceStore:
    """线程安全的工作区表。所有返回值都是副本。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or default_store_path()
        self._lock = threading.RLock()
        self._workspaces: List[Dict[str, Any]] = []
        self._load()

    # ── 持久化 ──────────────────────────────────────────────────────

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, encoding="utf-8") as handle:
            data = json.load(handle)
        workspaces = data.get("workspaces") if isinstance(data, dict) else None
        if not isinstance(workspaces, list):
            raise StoreError(f"远程工作区配置损坏（未覆盖原文件）: {self._path}")
        migrate = False
        for w in workspaces:
            if not isinstance(w, dict) or not isinstance(w.get("id"), str):
                raise StoreError(f"远程工作区配置损坏（未覆盖原文件）: {self._path}")
            enc = w.pop("token_enc", None)
            if isinstance(enc, str):
                try:
                    from backend.services.secret_box import decrypt_secret

                    token = decrypt_secret(enc)
                except Exception:  # noqa: BLE001 — 换机器/换用户后 DPAPI 无法解密
                    token = ""
                if len(token) != 64:
                    logger.warning("remote_mcp: token for workspace %s could not be decrypted; reset", w["id"])
                    token = secrets.token_hex(32)
                    w["enabled"] = False
                    w["token_reset"] = True
                    migrate = True
                w["token"] = token
            elif isinstance(w.get("token"), str):
                migrate = True  # 旧版明文 → 加密重写
            else:
                w["token"] = secrets.token_hex(32)
                w["enabled"] = False
                w["token_reset"] = True
                migrate = True
            if w.get("approval") not in APPROVAL_MODES:
                w["approval"] = "auto"
        self._workspaces = workspaces
        if migrate:
            self._save()

    @staticmethod
    def _encrypt(workspace: Dict[str, Any]) -> Dict[str, Any]:
        from backend.services.secret_box import encrypt_secret

        row = {k: v for k, v in workspace.items() if k != "token"}
        row["token_enc"] = encrypt_secret(workspace["token"], account=f"remote-mcp:{workspace['id']}")
        return row

    def _save(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        temp = f"{self._path}.{uuid.uuid4().hex}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "workspaces": [self._encrypt(w) for w in self._workspaces]},
                      handle, ensure_ascii=False, indent=2)
        with contextlib.suppress(OSError):
            Path(temp).chmod(0o600)
        Path(temp).replace(self._path)

    # ── 查询 ────────────────────────────────────────────────────────

    @staticmethod
    def public_view(workspace: Dict[str, Any]) -> Dict[str, Any]:
        return {k: copy.deepcopy(v) for k, v in workspace.items() if k != "token"}

    def list_public(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self.public_view(w) for w in self._workspaces]

    def get(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for w in self._workspaces:
                if w["id"] == workspace_id:
                    return copy.deepcopy(w)
        return None

    def find_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """常量时间比对 token；只返回 enabled 的工作区。"""
        if not isinstance(token, str) or len(token) != 64:
            return None
        found = None
        with self._lock:
            for w in self._workspaces:
                if secrets.compare_digest(token, w.get("token", "")) and w.get("enabled"):
                    found = copy.deepcopy(w)
        return found

    def connection_token(self, workspace_id: str) -> str:
        workspace = self.get(workspace_id)
        if workspace is None:
            raise StoreError("工作区不存在")
        if not workspace.get("enabled"):
            raise StoreError("工作区已停用")
        return workspace["token"]

    # ── 变更 ────────────────────────────────────────────────────────

    def create(self, name: str, root: str) -> Dict[str, Any]:
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise StoreError("请输入 1-80 个字符的名称")
        if not isinstance(root, str) or not root.strip():
            raise StoreError("请提供项目目录")
        canonical = os.path.realpath(Path(root).expanduser())
        if not os.path.isdir(canonical):
            raise StoreError("必须选择已存在的目录")
        drive_root = os.path.abspath(os.sep) if os.name != "nt" else os.path.splitdrive(canonical)[0] + os.sep
        home = os.path.realpath(Path.home())
        if os.path.normcase(canonical) in {os.path.normcase(drive_root), os.path.normcase(home)}:
            raise StoreError("不能共享整个磁盘或用户主目录，请选择具体项目")
        workspace = {
            "id": str(uuid.uuid4()),
            "name": name.strip(),
            "root": canonical,
            "token": secrets.token_hex(32),
            "enabled": True,
            "permissions": {"read": True, "write": False, "shell": False},
            "approval": "auto",
            "created_at": _now(),
            "rotated_at": None,
        }
        with self._lock:
            self._workspaces.append(workspace)
            self._save()
        return self.public_view(workspace)

    def update(self, workspace_id: str, *, enabled: Optional[bool] = None,
               permissions: Optional[Dict[str, bool]] = None,
               approval: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            workspace = self._require(workspace_id)
            if approval is not None:
                if approval not in APPROVAL_MODES:
                    raise StoreError(f"无效审批模式: {approval}")
                workspace["approval"] = approval
            if enabled is not None:
                if not isinstance(enabled, bool):
                    raise StoreError("enabled 必须是布尔值")
                workspace["enabled"] = enabled
            for key, value in (permissions or {}).items():
                if key not in PERMISSION_KEYS or not isinstance(value, bool):
                    raise StoreError(f"无效权限项: {key}")
                if key == "read" and not value:
                    raise StoreError("read 权限不可关闭（请停用工作区）")
                workspace["permissions"][key] = value
            self._save()
            return self.public_view(workspace)

    def rotate(self, workspace_id: str) -> Dict[str, Any]:
        with self._lock:
            workspace = self._require(workspace_id)
            workspace["token"] = secrets.token_hex(32)
            workspace["rotated_at"] = _now()
            workspace.pop("token_reset", None)
            self._save()
            return self.public_view(workspace)

    def remove(self, workspace_id: str) -> None:
        with self._lock:
            self._require(workspace_id)
            self._workspaces = [w for w in self._workspaces if w["id"] != workspace_id]
            self._save()

    def _require(self, workspace_id: str) -> Dict[str, Any]:
        for w in self._workspaces:
            if w["id"] == workspace_id:
                return w
        raise StoreError("工作区不存在")


__all__ = ["APPROVAL_MODES", "PERMISSION_KEYS", "StoreError", "WorkspaceStore", "default_store_path"]
