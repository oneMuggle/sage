"""Persistent master key for the arena account pool.

Why this module exists (P0 bug fix, docs/mcp-aren-card-port-plan.md §1.3-A):
    Spec §7.1 derived the Fernet key from ``SAGE_LOCAL_AUTH_TOKEN``. That value
    is regenerated on *every* backend start — ``electron/main.ts`` does
    ``randomBytes(32)`` per generation and ``backend/api/local_auth.py`` does
    ``secrets.token_urlsafe(32)`` for standalone/dev runs — so every stored
    password would become undecryptable after a restart, breaking spec G4
    ("cross-restart persistence").

    Fix: persist a random 32-byte secret next to the account DB and derive the
    Fernet key from *that* secret plus the stable machine id. The KDF itself is
    unchanged (``derive_arena_key``: PBKDF2-HMAC-SHA256, 480k iterations).

Threat model: the backend only listens on loopback, but loopback is not an
authorization boundary (see backend/api/local_auth.py). The key file is written
0600 and lives in the per-user data dir; DPAPI wrapping is a future hardening
step (tracked in the plan) and intentionally not a hard dependency here.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Optional

from backend.services.arena_accounts import derive_arena_key
from backend.utils.machine_id import machine_id

logger = logging.getLogger(__name__)

#: File name of the persisted master secret inside the arena data dir.
MASTER_KEY_FILE = "master.key"

#: Account DB file name inside the arena data dir.
ARENA_DB_FILE = "arena.sqlite"

_KEY_BYTES = 32


class ArenaKeystoreError(RuntimeError):
    """Raised when the arena master key cannot be read or created."""


def arena_data_dir(data_dir: Optional[str] = None) -> Path:
    """Resolve the writable arena data dir.

    Follows the ``SAGE_USER_DATA_DIR`` convention established for
    scheduled_tasks.json / themes (backend/main.py:403-412): packaged builds
    write to ``%AppData%/Sage``, dev runs fall back to ``<project>/backend/data``.
    """
    if data_dir:
        return Path(data_dir)
    env = os.environ.get("SAGE_USER_DATA_DIR")
    base = Path(env) if env else Path("backend/data")
    return base / "arena"


def master_key_path(data_dir: Optional[str] = None) -> Path:
    return arena_data_dir(data_dir) / MASTER_KEY_FILE


def arena_db_path(data_dir: Optional[str] = None) -> Path:
    return arena_data_dir(data_dir) / ARENA_DB_FILE


def _atomic_write_private(path: Path, payload: bytes) -> None:
    """Write ``payload`` to ``path`` atomically with 0600 permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".master-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        try:
            # POSIX: owner-only. On Windows chmod only toggles the readonly bit,
            # which is why the file also lives under the per-user profile.
            os.chmod(tmp_name, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_or_create_master_key(data_dir: Optional[str] = None) -> str:
    """Return the base64 master secret, creating it on first use."""
    path = master_key_path(data_dir)
    if path.is_file():
        try:
            raw = path.read_bytes().strip()
        except OSError as exc:
            raise ArenaKeystoreError(f"cannot read arena master key {path}: {exc}") from exc
        if raw:
            return raw.decode("ascii", "replace")
        logger.warning("arena master key file is empty; regenerating (%s)", path)
    secret = base64.urlsafe_b64encode(secrets.token_bytes(_KEY_BYTES)).decode("ascii")
    try:
        _atomic_write_private(path, secret.encode("ascii"))
    except OSError as exc:
        # e.g. the path exists as a directory, or the data dir is read-only
        raise ArenaKeystoreError(f"cannot write arena master key {path}: {exc}") from exc
    logger.info("arena master key created at %s", path)
    return secret


def arena_fernet_key(data_dir: Optional[str] = None) -> bytes:
    """Fernet key = PBKDF2(master secret, salt=machine_id, 480k) per spec §7.1."""
    return derive_arena_key(load_or_create_master_key(data_dir), machine_id())
