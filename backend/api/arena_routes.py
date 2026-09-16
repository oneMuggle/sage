"""FastAPI router for arena account management.

All endpoints check the feature flag and return 403 when disabled.
The service is a module-level singleton initialized in main.py lifespan.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from backend.config.arena_automation import ArenaAutomationConfig
from backend.services.arena_accounts import (
    AccountState, ArenaAccountService,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/arena", tags=["arena"])


#: Module-level singleton; set by init_arena_service() in main.py lifespan
_service: Optional[ArenaAccountService] = None
_config: Optional[ArenaAutomationConfig] = None
_service_lock = threading.Lock()


class CreateAccountRequest(BaseModel):
    email: str
    password: str
    notes: Optional[str] = None


def _strip_password(acc: Optional[dict]) -> Optional[dict]:
    if acc is None:
        return None
    return {k: v for k, v in acc.items() if k != "password"}


def init_arena_service(
    db_path: str,
    encryption_key: bytes,
    config: ArenaAutomationConfig,
) -> ArenaAccountService:
    """Initialize the singleton service. Call from main.py lifespan."""
    global _service, _config
    with _service_lock:
        _config = config
        _service = ArenaAccountService(
            db_path=db_path,
            encryption_key=encryption_key,
            failure_threshold=config.failure_isolation_threshold,
        )
        return _service


def get_service() -> ArenaAccountService:
    if _service is None:
        raise HTTPException(status_code=503, detail="arena service not initialized")
    return _service


def _check_enabled() -> None:
    if _config is None or not _config.enabled:
        raise HTTPException(status_code=403, detail="arena automation is disabled")


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(
    body: CreateAccountRequest,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    if _config and len(svc.list_accounts()) >= _config.max_accounts:
        raise HTTPException(
            status_code=409,
            detail=f"max_accounts ({_config.max_accounts}) reached",
        )
    try:
        acc = svc.create_account(email=body.email, password=body.password, notes=body.notes)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _strip_password(acc)


@router.get("/accounts")
def list_accounts(
    state: Optional[str] = None,
    svc: ArenaAccountService = Depends(get_service),
) -> List[dict]:
    _check_enabled()
    if state is not None:
        try:
            state_enum = AccountState(state)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid state: {state}")
        return [_strip_password(a) for a in svc.list_accounts(state=state_enum)]
    return [_strip_password(a) for a in svc.list_accounts()]


@router.get("/accounts/{account_id}")
def get_account(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    acc = svc.get_account(account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    return _strip_password(acc)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def soft_delete_account(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
):
    _check_enabled()
    if svc.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    svc.soft_delete_account(account_id)


@router.post("/accounts/{account_id}/isolate")
def isolate_account(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    acc = svc.get_account(account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    svc.record_failure(account_id, reason="manual_isolate")
    # bump count past threshold
    while svc.get_account(account_id)["state"] != AccountState.DISABLED.value:
        svc.record_failure(account_id, reason="manual_isolate")
    return _strip_password(svc.get_account(account_id))


@router.post("/accounts/{account_id}/enable")
def enable_account(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    if svc.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    svc.enable_account(account_id)
    return _strip_password(svc.get_account(account_id))


@router.get("/accounts/{account_id}/stats")
def get_stats(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    acc = svc.get_account(account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    return {
        "id": acc["id"],
        "state": acc["state"],
        "failure_count": acc["failure_count"],
        "last_used_at": acc["last_used_at"],
        "isolated_at": acc["isolated_at"],
    }
