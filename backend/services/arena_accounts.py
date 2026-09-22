"""Arena account pool: SQLite storage with Fernet-encrypted credentials.

State machine:
  available -> reserved -> available (on release)
  available -> degraded (on first failure)
  degraded  -> available (on release, resets count)
  degraded  -> disabled (when failure_count reaches threshold)
  *         -> destroyed (on soft_delete)
  disabled  -> available (on manual enable_account)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cryptography 惰性加载 (2026-09-21 Win7 alpha.51 启动崩溃修复)
#
# 背景：cryptography 47.0.0 在部分 Win7 SP1 机器上加载失败（KB3033929 缺失
# 或 AV 拦截 Rust 扩展），导致整个后端无法启动。Arena 自动化是可选功能，
# 不应因 cryptography 不可用而阻塞启动。
#
# 方案：将 cryptography 导入改为惰性加载，首次调用时才 import；提供
# ``crypto_available()`` 探测函数供 main.py 启动期判断；加载失败时 log
# 清晰错误但不抛异常，让 main.py 跳过 arena 装配继续启动。
# ---------------------------------------------------------------------------

_CRYPTO_CACHE: Optional[Dict[str, Any]] = None
_CRYPTO_LOAD_ERROR: Optional[str] = None


def _lazy_crypto() -> Optional[Dict[str, Any]]:
    """惰性加载 cryptography 原语，缓存首次成功结果。

    Returns
    -------
    dict or None
        ``{"Fernet": ..., "hashes": ..., "PBKDF2HMAC": ...}`` 或 None（不可用）。
        不可用时会设置 ``_CRYPTO_LOAD_ERROR`` 并 log warning。
    """
    global _CRYPTO_CACHE, _CRYPTO_LOAD_ERROR
    if _CRYPTO_CACHE is not None:
        return _CRYPTO_CACHE
    if _CRYPTO_LOAD_ERROR is not None:
        # 已经尝试过且失败了，不重复尝试（避免启动期多次 log）
        return None
    try:
        from cryptography.fernet import Fernet  # noqa: WPS433 — 惰性导入
        from cryptography.hazmat.primitives import hashes  # noqa: WPS433
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: WPS433

        _CRYPTO_CACHE = {
            "Fernet": Fernet,
            "hashes": hashes,
            "PBKDF2HMAC": PBKDF2HMAC,
        }
        logger.debug("cryptography 加载成功")
        return _CRYPTO_CACHE
    except Exception as e:  # noqa: BLE001 — 任何导入失败（ImportError / OSError / C-level panic）
        _CRYPTO_LOAD_ERROR = f"{type(e).__name__}: {e}"
        logger.warning(
            "cryptography 不可用（Arena 自动化将被禁用）: %s — "
            "可能原因：Win7 缺少 KB3033929 / cryptography 47.0.0 Rust 扩展被 AV 拦截 / "
            "Python embeddable 目录损坏",
            _CRYPTO_LOAD_ERROR,
        )
        return None


def crypto_available() -> bool:
    """探测 cryptography 是否可加载。

    在 main.py 启动期调用，决定是否装配 Arena 服务。惰性：首次调用时尝试
    加载，后续调用直接返回缓存结果。
    """
    return _lazy_crypto() is not None


def derive_arena_key(token: str, machine_id: str) -> bytes:
    """Derive a Fernet-compatible key per Spec §7.1.

    Uses PBKDF2-HMAC-SHA256 with the machine_id as salt and 480,000 iterations,
    producing a 32-byte key that is urlsafe-base64 encoded for Fernet consumption.

    Raises
    ------
    RuntimeError
        cryptography 不可用时抛出，调用方应捕获并降级。
    """
    import base64

    crypto = _lazy_crypto()
    if crypto is None:
        raise RuntimeError(
            f"derive_arena_key: cryptography 不可用（{_CRYPTO_LOAD_ERROR}）"
        )
    PBKDF2HMAC = crypto["PBKDF2HMAC"]
    hashes = crypto["hashes"]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=machine_id.encode("utf-8"),
        iterations=480_000,
    )
    raw = kdf.derive(token.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


#: preferences 键：SecretBox 包装后的账号池 Fernet 主密钥（白名单见 settings_repo）
MASTER_KEY_PREFERENCE = "arena_master_key"


def get_or_create_master_key(settings_repo: Optional[Any] = None) -> bytes:
    """Load the account-pool Fernet master key, creating it on first use.

    The key is generated once, wrapped via SecretBox (Windows DPAPI / macOS
    keychain / Linux secret-tool) and stored in the preferences table under
    ``arena_master_key``. Losing the OS keystore entry therefore loses the
    stored passwords — that is inherent to the SecretBox scheme used across
    sage (same tradeoff as app_settings apiKey encryption).

    ``settings_repo`` is injectable for tests; defaults to SettingsRepository.

    Raises
    ------
    RuntimeError
        cryptography 不可用时抛出，调用方应捕获并降级（Arena 功能禁用）。
    """
    from backend.data.settings_repo import SettingsRepository
    from backend.services.secret_box import decrypt_secret, encrypt_secret

    crypto = _lazy_crypto()
    if crypto is None:
        raise RuntimeError(
            f"get_or_create_master_key: cryptography 不可用（{_CRYPTO_LOAD_ERROR}）"
        )
    Fernet = crypto["Fernet"]

    repo = settings_repo or SettingsRepository()
    stored = repo.get(MASTER_KEY_PREFERENCE)
    if stored:
        try:
            return decrypt_secret(stored).encode("utf-8")
        except Exception:  # noqa: BLE001 — keystore 丢失/换机器：重生成而非拒绝启动
            logger.warning(
                "arena_master_key 解包失败（OS 凭据库变更?），重新生成主密钥；"
                "旧账号池密码将无法解密"
            )
    key = Fernet.generate_key()
    repo.set(MASTER_KEY_PREFERENCE, encrypt_secret(key.decode("utf-8"), account="arena.master"))
    return key


def _utcnow_iso() -> str:
    """Return naive UTC timestamp string (timezone-aware now, tzinfo stripped)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")  # noqa: UP017


class AccountState(Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    DESTROYED = "destroyed"


#: Default failure threshold before account is auto-disabled
DEFAULT_FAILURE_THRESHOLD = 3


class ArenaCredentialError(RuntimeError):
    """Stored credentials cannot be decrypted (lost master.key / machine change).

    ``capabilities`` 与账号列表必须继续可用（UI 要能解释原因），只有
    涉及明文密读的路径才抛本异常。
    """


_SCHEMA = """
CREATE TABLE IF NOT EXISTS arena_accounts (
    id              TEXT PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_enc    BLOB NOT NULL,
    state           TEXT NOT NULL DEFAULT 'available',
    last_used_at    TEXT,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    isolated_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    notes           TEXT,
    proxy_url       TEXT,
    proxy_sid       TEXT,
    exit_ip         TEXT,
    credits,
    user_id         TEXT,
    last_draw_at    TEXT,
    draw_count      INTEGER NOT NULL DEFAULT 0,
    source          TEXT
);
CREATE INDEX IF NOT EXISTS idx_arena_accounts_state
    ON arena_accounts(state);
CREATE TABLE IF NOT EXISTS arena_draws (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arena_draws_account
    ON arena_draws(account_id);
"""

#: P2 新增列（ArenCard 移植前旧库经 ALTER TABLE 原地补齐）。
#: credits 刻意不带类型（BLOB affinity）：注册结果给 str("15000")、
#: 手动更新给 int(500)，sqlite 原样存取，两侧断言都成立。
_MIGRATION_COLUMNS = (
    ("proxy_url", "TEXT"),
    ("proxy_sid", "TEXT"),
    ("exit_ip", "TEXT"),
    ("credits", ""),
    ("user_id", "TEXT"),
    ("last_draw_at", "TEXT"),
    ("draw_count", "INTEGER NOT NULL DEFAULT 0"),
    ("source", "TEXT"),
)

_ACCOUNT_COLUMNS = (
    "id", "email", "password_enc", "state", "last_used_at", "failure_count",
    "isolated_at", "created_at", "updated_at", "notes",
    "proxy_url", "proxy_sid", "exit_ip", "credits", "user_id",
    "last_draw_at", "draw_count", "source",
)


class ArenaAccountService:
    """Thread-safe account pool backed by SQLite."""

    def __init__(
        self,
        db_path: str,
        encryption_key: bytes,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    ):
        crypto = _lazy_crypto()
        if crypto is None:
            raise RuntimeError(
                f"ArenaAccountService: cryptography 不可用（{_CRYPTO_LOAD_ERROR}）"
            )
        Fernet = crypto["Fernet"]
        self._db_path = db_path
        self._fernet = Fernet(encryption_key)
        self._failure_threshold = failure_threshold
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Additive in-place migration for pre-port databases (plan §5.3).

        幂等：逐列探测缺失再 ALTER；arena_draws 用 IF NOT EXISTS。
        旧库既有数据（notes 等）原样保留。
        """
        with self._lock:
            existing = {
                row[1] for row in self._conn.execute("PRAGMA table_info(arena_accounts)")
            }
            for name, ddl in _MIGRATION_COLUMNS:
                if name in existing:
                    continue
                # ALTER TABLE 的列定义允许空类型（credits 无亲和性，原样存取）
                self._conn.execute(f"ALTER TABLE arena_accounts ADD COLUMN {name} {ddl}")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arena_draws (
                    id          TEXT PRIMARY KEY,
                    account_id  TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    payload     TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_arena_draws_account
                    ON arena_draws(account_id);
                """
            )
            self._conn.commit()

    # -- CRUD -------------------------------------------------------------

    def create_account(
        self,
        email: str,
        password: str,
        notes: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Dict:
        with self._lock:
            now = _utcnow_iso()
            account_id = str(uuid.uuid4())
            password_enc = self._fernet.encrypt(password.encode("utf-8"))
            try:
                self._conn.execute(
                    """
                    INSERT INTO arena_accounts
                    (id, email, password_enc, state, failure_count,
                     created_at, updated_at, notes, source)
                    VALUES (?, ?, ?, 'available', 0, ?, ?, ?, ?)
                    """,
                    (account_id, email, password_enc, now, now, notes, source),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError(f"email {email!r} already exists") from e
            return {
                "id": account_id,
                "email": email,
                "state": AccountState.AVAILABLE.value,
                "failure_count": 0,
                "created_at": now,
            }

    def list_accounts(self, state: Optional[AccountState] = None) -> List[Dict]:
        with self._lock:
            if state is not None:
                rows = self._conn.execute(
                    "SELECT id FROM arena_accounts WHERE state = ? ORDER BY created_at",
                    (state.value,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id FROM arena_accounts ORDER BY created_at"
                ).fetchall()
            return [self.get_account(r[0]) for r in rows if self.get_account(r[0])]

    def get_account(self, account_id: str, include_secret: bool = False) -> Optional[Dict]:
        """Return the account projection; secrets are strictly opt-in.

        默认（include_secret=False）不读密文、不含 password 键——列表/详情
        在 master.key 丢失时依然可用（UI 要能解释原因）。include_secret=True
        才解密；解密失败抛 ArenaCredentialError 而不是炸掉调用方。
        """
        with self._lock:
            cols = ", ".join(_ACCOUNT_COLUMNS)
            row = self._conn.execute(
                f"SELECT {cols} FROM arena_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return None
            # noqa 下行 B905：zip strict= 是 3.10+ 形参（py38 运行时 TypeError）；
            # cols 即 _ACCOUNT_COLUMNS 的 SELECT 投影，长度恒等，strict 检查冗余
            acc: Dict[str, Any] = dict(zip(_ACCOUNT_COLUMNS, row))  # noqa: B905
            acc.pop("password_enc")
            if include_secret:
                acc["password"] = self._decrypt_password(row[2])
            return acc

    def get_secret(self, account_id: str) -> Optional[str]:
        """Decrypt and return the stored password; None when account missing."""
        with self._lock:
            row = self._conn.execute(
                "SELECT password_enc FROM arena_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            return None
        return self._decrypt_password(row[0])

    def _decrypt_password(self, password_enc: bytes) -> str:
        try:
            return self._fernet.decrypt(password_enc).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — 统一转译为凭据错误（含 InvalidToken）
            raise ArenaCredentialError(
                "账号密文无法解密：master key 丢失或已更换；"
                "账号池仍可读，但明文密码不可恢复"
            ) from exc

    def credentials_readable(self) -> bool:
        """Probe whether stored credentials can be decrypted. 空库 = True。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT password_enc FROM arena_accounts LIMIT 1"
            ).fetchone()
        if row is None:
            return True
        try:
            self._decrypt_password(row[0])
        except ArenaCredentialError:
            return False
        return True

    def count_accounts(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM arena_accounts"
            ).fetchone()
            return int(row[0]) if row else 0

    # -- P2：代理绑定 / 额度 / 抽卡历史 --------------------------------------

    def update_binding(
        self,
        account_id: str,
        proxy_url: str,
        proxy_sid: Optional[str] = None,
        exit_ip: Optional[str] = None,
    ) -> None:
        """Bind a proxy exit to the account (rotation bookkeeping)."""
        with self._lock:
            now = _utcnow_iso()
            self._conn.execute(
                "UPDATE arena_accounts SET proxy_url = ?, proxy_sid = ?, "
                "exit_ip = ?, updated_at = ? WHERE id = ?",
                (proxy_url, proxy_sid, exit_ip, now, account_id),
            )
            self._conn.commit()

    def update_credits(self, account_id: str, credits: Any, user_id: Optional[str] = None) -> None:
        with self._lock:
            now = _utcnow_iso()
            self._conn.execute(
                "UPDATE arena_accounts SET credits = ?, user_id = ?, "
                "updated_at = ? WHERE id = ?",
                (credits, user_id, now, account_id),
            )
            self._conn.commit()

    def record_draw(self, account_id: str, payload: Dict[str, Any]) -> str:
        """Append one draw record and bump the account's draw counters."""
        draw_id = str(uuid.uuid4())
        now = _utcnow_iso()
        with self._lock:
            import json as _json

            self._conn.execute(
                "INSERT INTO arena_draws (id, account_id, created_at, payload) "
                "VALUES (?, ?, ?, ?)",
                (draw_id, account_id, now, _json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.execute(
                "UPDATE arena_accounts SET draw_count = draw_count + 1, "
                "last_draw_at = ?, updated_at = ? WHERE id = ?",
                (now, now, account_id),
            )
            self._conn.commit()
        return draw_id

    def list_draws(
        self,
        account_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Newest-first draw records; payload keys are projected at top level."""
        import json as _json

        with self._lock:
            if account_id is not None:
                rows = self._conn.execute(
                    "SELECT id, account_id, created_at, payload FROM arena_draws "
                    "WHERE account_id = ? ORDER BY rowid DESC LIMIT ?",
                    (account_id, int(limit)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, account_id, created_at, payload FROM arena_draws "
                    "ORDER BY rowid DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        results: List[Dict[str, Any]] = []
        for draw_id, acct, created_at, payload in rows:
            try:
                data = _json.loads(payload)
            except ValueError:
                data = {"raw": payload}
            if not isinstance(data, dict):
                data = {"raw": data}
            results.append(
                {"id": draw_id, "account_id": acct, "created_at": created_at, **data}
            )
        return results

    # -- Scheduling -------------------------------------------------------

    def reserve_account(self) -> Optional[Dict]:
        """Pick the available account with oldest last_used_at (LRU)."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id FROM arena_accounts
                WHERE state = 'available'
                ORDER BY
                    CASE WHEN last_used_at IS NULL THEN 1 ELSE 0 END,
                    last_used_at ASC
                LIMIT 1
                """,
            ).fetchone()
            if row is None:
                return None
            now = _utcnow_iso()
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'reserved', "
                "last_used_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row[0]),
            )
            self._conn.commit()
            return self.get_account(row[0])

    def release_account(self, account_id: str) -> None:
        with self._lock:
            now = _utcnow_iso()
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'available', "
                "failure_count = 0, updated_at = ? WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def record_failure(self, account_id: str, reason: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT failure_count FROM arena_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return
            new_count = row[0] + 1
            new_state = "degraded"
            isolated_at = None
            if new_count >= self._failure_threshold:
                new_state = "disabled"
                isolated_at = _utcnow_iso()
            now = _utcnow_iso()
            self._conn.execute(
                "UPDATE arena_accounts SET state = ?, failure_count = ?, "
                "isolated_at = ?, updated_at = ? WHERE id = ?",
                (new_state, new_count, isolated_at, now, account_id),
            )
            self._conn.commit()
            logger.info(
                "arena account %s failure recorded: count=%d state=%s reason=%s",
                account_id, new_count, new_state, reason,
            )

    def enable_account(self, account_id: str) -> None:
        with self._lock:
            now = _utcnow_iso()
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'available', "
                "failure_count = 0, isolated_at = NULL, updated_at = ? "
                "WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def soft_delete_account(self, account_id: str) -> None:
        with self._lock:
            now = _utcnow_iso()
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'destroyed', updated_at = ? "
                "WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
