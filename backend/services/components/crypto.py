"""RSA-SHA256 verification and public-key resolution for component packs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .errors import ComponentError


def load_public_key(pem: bytes):
    try:
        return serialization.load_pem_public_key(pem)
    except (ValueError, TypeError) as exc:
        raise ComponentError("组件签名公钥格式无效", code="public_key_invalid") from exc


def verify_signature(public_key, payload: bytes, signature: bytes) -> bool:
    try:
        public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        return False


def resolve_public_key_pem(
    *,
    environ: Optional[Mapping[str, str]] = None,
    user_data_dir: Optional[Path] = None,
    resources_dir: Optional[Path] = None,
) -> Optional[bytes]:
    """Resolve the trusted public key.

    Order: explicit path -> inline PEM -> per-user key -> packaged key.
    Returning ``None`` is a hard failure at install time; callers must not
    silently accept unsigned packages.
    """
    env = environ if environ is not None else os.environ
    explicit = str(env.get("SAGE_COMPONENT_PUBLIC_KEY_PATH", "")).strip()
    if explicit:
        path = Path(explicit)
        return path.read_bytes() if path.is_file() else None
    inline = env.get("SAGE_COMPONENT_PUBLIC_KEY")
    if inline:
        return inline.encode("utf-8")
    candidates = []
    if user_data_dir is not None:
        candidates.append(user_data_dir / "components" / "public-key.pem")
    if resources_dir is not None:
        candidates.append(resources_dir / "component-public-key.pem")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_bytes()
    return None


def require_public_key(
    *,
    environ: Optional[Mapping[str, str]] = None,
    user_data_dir: Optional[Path] = None,
    resources_dir: Optional[Path] = None,
):
    pem = resolve_public_key_pem(
        environ=environ,
        user_data_dir=user_data_dir,
        resources_dir=resources_dir,
    )
    if not pem:
        raise ComponentError(
            "未配置组件签名公钥；请由管理员放置 component-public-key.pem "
            "或设置 SAGE_COMPONENT_PUBLIC_KEY_PATH",
            code="public_key_missing",
        )
    return load_public_key(pem)
