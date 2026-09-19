"""FastAPI router for arena account management.

All endpoints check the feature flag and return 403 when disabled.
The service is a module-level singleton initialized in main.py lifespan.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from backend.config.arena_automation import ArenaAutomationConfig
from backend.services.arena_accounts import (
    AccountState,
    ArenaAccountService,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/arena", tags=["arena"])


#: Module-level singletons; set by init_arena_service() / init_registration_service()
#: in main.py lifespan
_service: Optional[ArenaAccountService] = None
_config: Optional[ArenaAutomationConfig] = None
_registration: Optional[Any] = None
_observation: Optional[Any] = None
_service_lock = threading.Lock()
_obs_lock = threading.Lock()


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


# ---------------------------------------------------------------------------
# 单账号注册辅助（人工验证码 · 单实例，见 arena_registration.py 模块文档）
# ---------------------------------------------------------------------------

class SetPasswordRequest(BaseModel):
    password: str
    #: 用户已在浏览器里手动输入密码时跳过代填
    manual: bool = False


class AttachObservationRequest(BaseModel):
    browser_id: Optional[str] = None


def init_registration_service(
    config: ArenaAutomationConfig,
    account_service: Optional[ArenaAccountService] = None,
    service: Optional[Any] = None,
) -> Any:
    """Initialize the registration-assist singleton. Call from main.py lifespan.

    ``service`` injects a pre-built (fake) instance for tests.
    """
    global _registration
    with _service_lock:
        if service is not None:
            _registration = service
        else:
            from backend.services.arena_registration import ArenaRegistrationService

            _registration = ArenaRegistrationService(
                config, account_service=account_service if account_service is not None else _service
            )
        return _registration


def get_registration() -> Any:
    if _registration is None:
        raise HTTPException(
            status_code=503, detail="arena registration service not initialized"
        )
    return _registration


@router.post("/register/start", status_code=status.HTTP_201_CREATED)
def start_registration(reg: Any = Depends(get_registration)) -> dict:
    _check_enabled()
    from backend.services.arena_registration import (
        RegistrationConflictError,
        RegistrationError,
    )

    try:
        return reg.start()
    except RegistrationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RegistrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/register/current")
def registration_status(reg: Any = Depends(get_registration)) -> dict:
    _check_enabled()
    from backend.services.arena_registration import RegistrationNotFoundError

    try:
        return reg.status()
    except RegistrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/register/current/open-verify")
def open_verification(reg: Any = Depends(get_registration)) -> dict:
    _check_enabled()
    from backend.services.arena_registration import (
        RegistrationConflictError,
        RegistrationError,
    )

    try:
        return reg.open_verification()
    except RegistrationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RegistrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/register/current/password")
def set_registration_password(
    body: SetPasswordRequest, reg: Any = Depends(get_registration)
) -> dict:
    _check_enabled()
    from backend.services.arena_registration import (
        RegistrationConflictError,
        RegistrationError,
    )

    try:
        return reg.set_password(body.password, manual=body.manual)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RegistrationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RegistrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/register/current/cancel")
def cancel_registration(reg: Any = Depends(get_registration)) -> dict:
    _check_enabled()
    from backend.services.arena_registration import RegistrationNotFoundError

    try:
        return reg.cancel()
    except RegistrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# 被动模型观测（复用 sage 自管浏览器的 CDP Network 事件，纯被动）
# ---------------------------------------------------------------------------

@router.post("/observations/attach")
def attach_observation(body: Optional[AttachObservationRequest] = None) -> dict:
    _check_enabled()
    global _observation
    from backend.services.arena_observation import ModelObservationService
    from backend.services.model_probe_worker import ModelProbeWorker
    from backend.tools.browser_cdp import BrowserCDPError, get_browser_manager

    def pump_factory(service: Any) -> Any:
        from backend.tools.browser_cdp import CdpEventPump

        return CdpEventPump(service._browser_session, on_event=service.process_event)

    with _obs_lock:
        if _observation is not None:
            _observation.stop()
            _observation = None
        try:
            session = get_browser_manager().require(
                body.browser_id if body is not None else None
            )
        except BrowserCDPError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        worker = ModelProbeWorker(
            backend=_config.probe_backend if _config is not None else "python"
        )
        service = ModelObservationService(
            session,
            worker,
            verdict_cap=_config.probe_evidence_cap if _config is not None else 500,
            pump_factory=pump_factory,
        )
        service.start()
        _observation = service
        return {"attached": True, "browser_id": getattr(session, "browser_id", "")}


@router.get("/observations")
def list_observations(limit: int = 20) -> dict:
    _check_enabled()
    with _obs_lock:
        service = _observation
        verdicts = service.get_recent_verdicts(limit) if service is not None else []
        return {"attached": service is not None, "verdicts": verdicts}


@router.post("/observations/detach")
def detach_observation() -> dict:
    _check_enabled()
    global _observation
    with _obs_lock:
        if _observation is not None:
            _observation.stop()
            _observation = None
        return {"attached": False}


def shutdown_arena_services() -> None:
    """Best-effort teardown. Call from main.py lifespan shutdown."""
    global _observation, _service
    with _obs_lock:
        if _observation is not None:
            with contextlib.suppress(Exception):
                _observation.stop()
            _observation = None
    with _service_lock:
        if _service is not None:
            with contextlib.suppress(Exception):
                _service.close()
            _service = None
