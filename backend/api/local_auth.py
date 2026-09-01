"""Process-local capability authentication for the desktop backend.

The backend only listens on loopback, but loopback is not an authorization
boundary: another local process can still call the HTTP API.  The Electron
supervisor passes a per-process capability in ``SAGE_LOCAL_AUTH_TOKEN``.
Standalone/dev launches without that variable get a fresh random capability;
the value is never returned by an API endpoint or written to logs.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status

_TOKEN_ENV = "SAGE_LOCAL_AUTH_TOKEN"
_OWNERSHIP_TOKEN_ENV = "SAGE_BACKEND_OWNERSHIP_TOKEN"
_OWNERSHIP_HEADER = "x-sage-backend-ownership"
_TOKEN_BYTES = 32
_PUBLIC_PATHS = frozenset({"/health", "/health/proof", "/api/v1/scheduled/health"})
_local_auth_token: Optional[str] = None


def ownership_health_proof(token: str, build_id: str, generation: int, pid: int) -> str:
    """Return a non-reversible proof binding health to the supervisor token."""
    message = f"sage-health-v1:{build_id}:{generation}:{pid}".encode()
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()


def is_ownership_health_valid(request: Request) -> bool:
    """Validate the supervisor-only ownership probe capability."""
    expected = os.environ.get(_OWNERSHIP_TOKEN_ENV)
    supplied = request.headers.get(_OWNERSHIP_HEADER)
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


def initialize_local_auth_token() -> str:
    """Read the injected capability or create one for this backend process."""
    global _local_auth_token
    configured = os.environ.get(_TOKEN_ENV)
    if configured:
        _local_auth_token = configured
    elif not _local_auth_token:
        _local_auth_token = secrets.token_urlsafe(_TOKEN_BYTES)
    return _local_auth_token


def get_local_auth_token() -> str:
    """Return the process capability, initializing it for test/dev imports."""
    return _local_auth_token or initialize_local_auth_token()


def is_local_auth_valid(request: Request) -> bool:
    """Return whether the selected local-auth header carries the capability.

    ``Authorization`` is the canonical header.  When it is present (including
    an explicitly empty value), do not fall back to the compatibility header;
    otherwise a client could not reliably clear inherited credentials.
    """
    expected = get_local_auth_token()
    authorization = request.headers.get("authorization")
    compatibility = request.headers.get("x-sage-local-authorization", "")
    # LLM proxy requests legitimately carry the provider's Authorization API key.
    # Electron's capability header remains the local authentication authority for
    # this route, without exposing the provider key to the local-auth parser.
    if (request.url.path.startswith("/api/v1/llm/") and compatibility) or authorization is None:
        authorization = compatibility

    scheme, separator, supplied = authorization.partition(" ")
    return bool(
        separator
        and scheme.lower() == "bearer"
        and supplied
        and hmac.compare_digest(supplied, expected)
    )


def is_public_path(path: str) -> bool:
    """Return whether a path is needed by a supervisor before authentication."""
    return path in _PUBLIC_PATHS


def require_local_auth(
    request: Request,
) -> None:
    """Require an exact Bearer capability without exposing token details."""
    if not is_local_auth_valid(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="本地授权凭据无效或缺失",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Make direct route-module imports safe while lifespan is not running (for tests
# and ASGI embedding). Production lifespan re-reads the environment explicitly.
initialize_local_auth_token()
