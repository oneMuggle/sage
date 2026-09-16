"""MCP OAuth token 持久化存储（切片 2，r61）。

按服务器名保存/读取 OAuth token 记录（切片 3 授权流的消费者侧）。
文件 ``<user_data_dir>/mcp_oauth_tokens.json``，与 mcp_servers.json
同根同口径；记录不存在时读取方行为与"未配置 OAuth"完全一致。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

TOKENS_FILE = "mcp_oauth_tokens.json"


@dataclass
class TokenRecord:
    """一个 MCP 服务器的 OAuth token（含刷新所需的服务器元数据）。"""

    server_name: str
    access_token: str
    token_type: str = "Bearer"
    #: epoch 秒；0 = 服务器未回传过期时间（视为不过期）
    expires_at: float = 0.0
    refresh_token: str = ""
    scope: str = ""
    #: 刷新所需（切片 3 授权成功时回填）
    client_id: str = ""
    token_endpoint: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Optional[TokenRecord]:
        """形状非法返回 None（调用方跳过该条，不整体失败）。"""
        if not isinstance(data, dict):
            return None
        name = data.get("server_name")
        token = data.get("access_token")
        if not isinstance(name, str) or not name:
            return None
        if not isinstance(token, str) or not token:
            return None
        expires_at = data.get("expires_at", 0.0)
        if not isinstance(expires_at, (int, float)):
            expires_at = 0.0
        return cls(
            server_name=name,
            access_token=token,
            token_type=data.get("token_type") if isinstance(data.get("token_type"), str) else "Bearer",
            expires_at=float(expires_at),
            refresh_token=data.get("refresh_token") if isinstance(data.get("refresh_token"), str) else "",
            scope=data.get("scope") if isinstance(data.get("scope"), str) else "",
            client_id=data.get("client_id") if isinstance(data.get("client_id"), str) else "",
            token_endpoint=data.get("token_endpoint") if isinstance(data.get("token_endpoint"), str) else "",
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        )


def _default_root() -> Path:
    user_data_dir = os.environ.get("SAGE_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir)
    return Path("data")


class OAuthTokenStore:
    """mcp_oauth_tokens.json 的进程内句柄（写后即落盘，跨进程读最新）。"""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else _default_root()

    @property
    def path(self) -> Path:
        return self.root / TOKENS_FILE

    def _read_all(self) -> Dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("OAuth token 存储读取失败，按空表处理: %s", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write_all(self, records: Dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load(self, server_name: str) -> Optional[TokenRecord]:
        return TokenRecord.from_dict(self._read_all().get(server_name))

    def save(self, record: TokenRecord) -> None:
        records = self._read_all()
        records[record.server_name] = record.to_dict()
        self._write_all(records)

    def delete(self, server_name: str) -> bool:
        records = self._read_all()
        if server_name not in records:
            return False
        del records[server_name]
        self._write_all(records)
        return True

    def list_names(self) -> list:
        return sorted(self._read_all().keys())


_store_lock = threading.Lock()
_store: Optional[OAuthTokenStore] = None


def get_oauth_token_store() -> OAuthTokenStore:
    """进程级单例（根目录随 SAGE_USER_DATA_DIR，pool 同模式）。"""
    global _store
    with _store_lock:
        if _store is None:
            _store = OAuthTokenStore()
        return _store


def reset_oauth_token_store() -> None:
    """测试隔离用。"""
    global _store
    with _store_lock:
        _store = None
