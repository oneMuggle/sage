"""FastAPI router for arena account management.

All endpoints check the feature flag and return 403 when disabled.
The service is a module-level singleton initialized in main.py lifespan.
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
import threading
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

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
_config_path: Optional[str] = None
_db_path: Optional[str] = None
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
    config_path: Optional[str] = None,
) -> ArenaAccountService:
    """Initialize the singleton service. Call from main.py lifespan."""
    global _service, _config, _config_path, _db_path
    with _service_lock:
        _config = config
        _config_path = config_path
        _db_path = db_path
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


def shutdown_arena_service() -> None:
    """Full teardown: observation pump, registration assist, account pool,
    and the config/paths globals. Safe to call repeatedly / uninitialized."""
    global _observation, _service, _config, _config_path, _db_path, _registration
    with _obs_lock:
        if _observation is not None:
            with contextlib.suppress(Exception):
                _observation.stop()
            _observation = None
    with _service_lock:
        if _registration is not None:
            _registration = None
        if _service is not None:
            with contextlib.suppress(Exception):
                _service.close()
            _service = None
        _config = None
        _config_path = None
        _db_path = None


#: P0 名称（main.py lifespan 在用）——保持兼容别名
shutdown_arena_services = shutdown_arena_service


# ---------------------------------------------------------------------------
# 诊断端点（capabilities / config）——让 UI 能解释"为什么不可用"，
# 而不是裸 403/503。capabilities 永远 200；config 脱敏后 403 门控。
# ---------------------------------------------------------------------------

_REDACTED = "***redacted***"

#: HTTP 层默认后端（S0 结论：仓库 pin httpx，curl_cffi 为可选 fallback）
_DEFAULT_HTTP_BACKEND = "httpx"


def _browser_available() -> bool:
    """Detect a usable browser binary（复用 browser_cdp 的探测顺序）。"""
    try:
        from backend.tools.browser_cdp import discover_browser_executable

        return bool(discover_browser_executable())
    except Exception:  # noqa: BLE001 — 诊断端点永不因探测失败而 500
        return False


@router.get("/capabilities")
def get_capabilities() -> dict:
    config = _config
    master_on = bool(config and config.enabled)

    def _flag(sub_enabled: bool) -> bool:
        return master_on and bool(sub_enabled)

    service = _service
    mail_available: List[str] = []
    with contextlib.suppress(Exception):
        from backend.services.temporary_mail import available_providers

        mail_available = list(available_providers())
    token_window_ready = False
    if config is not None and config.enabled and config.token_window.enabled:
        with contextlib.suppress(Exception):
            from backend.services.arena_token_cache import get_token_window_cache

            token_window_ready = bool(get_token_window_cache(config).health()["ready"])
    return {
        "initialized": service is not None,
        "enabled": master_on,
        "flags": {
            "registration": _flag(bool(config.registration.enabled)) if config else False,
            "draw": _flag(bool(config.draw.enabled)) if config else False,
            "proxy": _flag(bool(config.proxy.enabled)) if config else False,
            "token_window": _flag(bool(config.token_window.enabled)) if config else False,
        },
        "config_path": _config_path or "",
        "http": {"default_backend": _DEFAULT_HTTP_BACKEND},
        "mail": {
            "configured": config.mail_provider if config else "",
            "available": mail_available,
        },
        # P3：token 窗口缓存（隐藏 Electron 窗口铸造 reCAPTCHA V3）
        "token_window": {
            "available": _flag(bool(config.token_window.enabled)) if config else False,
            "ready": token_window_ready,
        },
        "browser_path": {"available": _browser_available()},
        "data": {
            "credentials_readable": (
                service.credentials_readable() if service is not None else None
            ),
            "accounts_total": service.count_accounts() if service is not None else 0,
        },
    }


def _redact_secret(value: Any) -> Any:
    return _REDACTED if value else value


@router.get("/config")
def get_config() -> dict:
    _check_enabled()
    config = _config
    assert config is not None  # _check_enabled 已保证
    body = config.model_dump() if hasattr(config, "model_dump") else config.dict()
    proxy = body.get("proxy") or {}
    if proxy.get("api_token"):
        proxy["api_token"] = _REDACTED
    if proxy.get("pool_text"):
        proxy["pool_text"] = _REDACTED
    if body.get("mail_api_key"):
        body["mail_api_key"] = _REDACTED
    return body


# ---------------------------------------------------------------------------
# 批量注册 job（plan §5.8/§5.10）——编排实现在 arena_registration.py，
# 这里只做门控 + 编排接线。事件流契约与 orch_run_control 的 NDJSON 一致。
# ---------------------------------------------------------------------------

class StartRegistrationJobRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=50)
    concurrency: Optional[int] = Field(default=None, ge=1, le=10)
    #: off = 直连；pool = 走配置的代理池/API（需 proxy.enabled）
    proxy_mode: str = "off"


def _require_registration_enabled() -> None:
    if _config is None or not _config.enabled or not _config.registration.enabled:
        raise HTTPException(status_code=403, detail="registration is disabled")


def _require_proxy_enabled() -> None:
    if _config is None or not _config.enabled or not _config.proxy.enabled:
        raise HTTPException(status_code=403, detail="proxy is disabled")


def _job_or_404(job_id: str):
    from backend.services import arena_registration as arena_registration_svc

    job = arena_registration_svc.get_job_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/registration/jobs", status_code=status.HTTP_202_ACCEPTED)
def start_registration_job(body: StartRegistrationJobRequest) -> dict:
    _require_registration_enabled()
    proxy_mode = (body.proxy_mode or "off").strip().lower()
    if proxy_mode not in ("off", "pool"):
        raise HTTPException(
            status_code=400,
            detail=f"invalid proxy_mode: {body.proxy_mode!r}（可选 off / pool）",
        )
    proxy_provider: Any = None
    if proxy_mode == "pool":
        _require_proxy_enabled()
        from backend.services import arena_proxies

        proxy_provider = arena_proxies.provider_from_config(_config.proxy)
        if proxy_provider is None:
            raise HTTPException(
                status_code=400,
                detail="proxy pool/api not configured（pool_text 与 api_url 至少配一个）",
            )
    from backend.services import arena_registration as arena_registration_svc

    try:
        job_id = arena_registration_svc.start_job(
            count=body.count,
            concurrency=body.concurrency or _config.registration.concurrency,
            accounts_service=get_service(),
            config=_config,
            job_store=arena_registration_svc.get_job_store(),
            proxy_provider=proxy_provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": job_id, "status": "running"}


@router.get("/registration/jobs/{job_id}")
def get_registration_job(job_id: str) -> dict:
    _require_registration_enabled()
    return _job_or_404(job_id).snapshot()


@router.post("/registration/jobs/{job_id}/stop")
def stop_registration_job(job_id: str) -> dict:
    _require_registration_enabled()
    from backend.services import arena_registration as arena_registration_svc

    job = _job_or_404(job_id)
    arena_registration_svc.get_job_store().request_stop(job.id)
    return {"id": job.id, "status": job.status}


@router.get("/registration/jobs/{job_id}/results")
def list_registration_job_results(job_id: str) -> list:
    _require_registration_enabled()
    return _job_or_404(job_id).results


@router.get("/registration/jobs/{job_id}/export")
def export_registration_job(job_id: str) -> Response:
    _require_registration_enabled()
    from backend.services import arena_registration as arena_registration_svc

    _job_or_404(job_id)
    out_dir = (_config.data_dir or "") or tempfile.gettempdir()
    try:
        path = arena_registration_svc.export_accounts(
            job_id, out_dir, job_store=arena_registration_svc.get_job_store()
        )
    except ValueError as exc:
        if "unknown job" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    content = path.read_text(encoding="utf-8")
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/jobs/{job_id}/events")
def stream_job_events(job_id: str, after_seq: int = 0) -> Response:
    _require_registration_enabled()
    from backend.services import arena_registration as arena_registration_svc

    job = _job_or_404(job_id)
    events = arena_registration_svc.get_job_store().events_after(job.id, after_seq=after_seq)
    body = "\n".join(event.to_ndjson() for event in events)
    return Response(content=body, media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# 代理池 / 动态代理 API（plan §5.6，P2）——arena_proxies 服务的薄封装
# ---------------------------------------------------------------------------

class ProxyParseRequest(BaseModel):
    pool_text: str
    protocol: str = "http"


class ProxyTestRequest(BaseModel):
    #: 空串 = 直接探测本机出口 IP
    proxy_url: str = ""


class ProxyFetchRequest(BaseModel):
    country: str = ""
    protocol: str = "http"


@router.post("/proxies/parse")
def parse_proxies(body: ProxyParseRequest) -> dict:
    _require_proxy_enabled()
    from backend.services.arena_proxies import ProxyPool, display_proxy

    pool = ProxyPool(body.pool_text, protocol=body.protocol)
    return {
        "count": pool.count(),
        "items": [display_proxy(url) for url in pool.items()],
        "errors": list(pool.errors),
    }


@router.post("/proxies/test")
def test_proxy(body: ProxyTestRequest) -> dict:
    _require_proxy_enabled()
    from backend.services import arena_proxies

    if not body.proxy_url:
        return {
            "proxy_url": "",
            "exit_ip": arena_proxies.direct_exit_ip(),
            "alive": True,
        }
    return {
        "proxy_url": arena_proxies.display_proxy(body.proxy_url),
        "exit_ip": arena_proxies.proxy_exit_ip(body.proxy_url),
        "alive": arena_proxies.proxy_alive(body.proxy_url),
    }


@router.post("/proxies/fetch")
def fetch_proxy(body: ProxyFetchRequest) -> dict:
    _require_proxy_enabled()
    proxy_config = _config.proxy if _config is not None else None
    if proxy_config is None or not (
        (proxy_config.api_url or "").strip() and (proxy_config.api_token or "").strip()
    ):
        raise HTTPException(status_code=400, detail="proxy api not configured")
    from backend.services import arena_proxies

    api = arena_proxies.ProxyApi(
        api_url=proxy_config.api_url,
        token=proxy_config.api_token,
        country=body.country,
        protocol=body.protocol,
    )
    try:
        proxy_url = api.fetch()
        exit_ip = arena_proxies.proxy_exit_ip(proxy_url)
    except arena_proxies.ArenaProxyError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"proxy_url": proxy_url, "exit_ip": exit_ip}


# ---------------------------------------------------------------------------
# token 窗口（plan §5.9/§5.10，P3）——隐藏 Electron 窗口的驱动面。
# push 有门控（403/400）；state 与 health 是诊断式端点，永不 403：
# 窗口必须能拿到 enabled=false 才能优雅停轮询。
# ---------------------------------------------------------------------------

class TokenWindowPushRequest(BaseModel):
    token: str
    exit_ip: Optional[str] = None
    ua: Optional[str] = None


def _require_token_window_enabled() -> None:
    if _config is None or not _config.enabled or not _config.token_window.enabled:
        raise HTTPException(status_code=403, detail="token_window is disabled")


@router.post("/token-window/push")
def push_token(body: TokenWindowPushRequest) -> dict:
    _require_token_window_enabled()
    from backend.services.arena_token_cache import (
        ArenaTokenWindowError,
        get_token_window_cache,
    )

    cache = get_token_window_cache(_config)
    try:
        return cache.push(body.token, body.exit_ip, body.ua)
    except ArenaTokenWindowError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/token-window/state")
def token_window_state() -> dict:
    from backend.services.arena_token_cache import get_token_window_cache

    if _config is None or not _config.enabled:
        return {
            "enabled": False,
            "needed": False,
            "reject_count": 0,
            "want_proxy": False,
            "proxy_url": "",
            "poll_interval_sec": 2.0,
        }
    return get_token_window_cache(_config).state(enabled=_config.token_window.enabled)


@router.get("/token-window/health")
def token_window_health() -> dict:
    from backend.services.arena_token_cache import get_token_window_cache

    if _config is None or not _config.enabled:
        return {
            "ready": False,
            "count": 0,
            "error": "arena disabled",
            "exit_ip": "",
            "ua": "",
            "uptime": 0.0,
            "last_push_age": None,
        }
    return get_token_window_cache(_config).health()


#: main.py:712 的 lifespan 钩子调用复数名（P0 以来的历史名）——保留别名勿删。
shutdown_arena_services = shutdown_arena_service


# ---------------------------------------------------------------------------
# 抽卡任务（plan §2.2/§2.3/§5.8，P4）——编排实现在 arena_draw_engine.py，
# 这里只做门控 + 接线。事件流与注册 job 一致（NDJSON，after_seq 续传）。
# ---------------------------------------------------------------------------

class StartDrawJobRequest(BaseModel):
    #: 指定账号 id 列表；或 all_accounts=true 取全部 available 账号
    account_ids: List[str] = Field(default_factory=list)
    all_accounts: bool = False
    rounds_per_account: int = Field(default=1, ge=1, le=100)
    #: 空 = 继承 config.draw.keep_pattern（空 pattern = 全部命中保留）
    keep_pattern: str = ""
    #: None = 继承 config.draw.require_reasoning
    require_reasoning: Optional[bool] = None
    want_reasoning: bool = True
    #: 空 = 继承 config.draw.miss_action（archive/delete/keep）
    miss_action: str = ""
    rename_hit: bool = True
    #: None = 继承 config.draw.base_gap_sec
    base_gap_sec: Optional[float] = Field(default=None, ge=0.0, le=300.0)
    #: None = 继承 config.draw.switch_level（1-4 档；None=不换 IP）
    switch_level: Optional[int] = Field(default=None, ge=1, le=4)


def _require_draw_enabled() -> None:
    if _config is None or not _config.enabled or not _config.draw.enabled:
        raise HTTPException(status_code=403, detail="draw is disabled")


def _draw_proxy_provider() -> Any:
    """抽卡换 IP 用的代理池（proxy.enabled 且已配置时）；None = 直连。"""
    if _config is None or not _config.enabled or not _config.proxy.enabled:
        return None
    from backend.services.arena_proxies import provider_from_config

    return provider_from_config(_config.proxy)


def _draw_job_or_404(job_id: str):
    from backend.services import arena_draw_engine

    job = arena_draw_engine.get_job_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/draw/jobs", status_code=status.HTTP_202_ACCEPTED)
def start_draw_job(body: StartDrawJobRequest) -> dict:
    _require_draw_enabled()
    from backend.services import arena_draw_engine
    from backend.services.arena_token_cache import get_token_window_cache

    try:
        job_id = arena_draw_engine.start_draw_job(
            {
                "account_ids": body.account_ids,
                "all_accounts": body.all_accounts,
                "rounds_per_account": body.rounds_per_account,
                "keep_pattern": body.keep_pattern,
                "require_reasoning": body.require_reasoning,
                "want_reasoning": body.want_reasoning,
                "miss_action": body.miss_action,
                "rename_hit": body.rename_hit,
                "base_gap_sec": body.base_gap_sec,
                "switch_level": body.switch_level,
            },
            accounts_service=get_service(),
            config=_config,
            proxy_provider=_draw_proxy_provider(),
            token_cache=get_token_window_cache(_config),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": job_id, "status": "running"}


@router.get("/draw/jobs")
def list_draw_jobs() -> List[dict]:
    _require_draw_enabled()
    from backend.services import arena_draw_engine

    return arena_draw_engine.get_job_store().list()


@router.get("/draw/jobs/{job_id}")
def get_draw_job(job_id: str) -> dict:
    _require_draw_enabled()
    return _draw_job_or_404(job_id).snapshot()


@router.post("/draw/jobs/{job_id}/stop")
def stop_draw_job(job_id: str) -> dict:
    _require_draw_enabled()
    from backend.services import arena_draw_engine

    if not arena_draw_engine.get_job_store().request_stop(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return {"stopped": True}


@router.get("/draw/jobs/{job_id}/events")
def stream_draw_job_events(job_id: str, after_seq: int = 0) -> Response:
    _require_draw_enabled()
    from backend.services import arena_draw_engine

    job = _draw_job_or_404(job_id)
    events = arena_draw_engine.get_job_store().events_after(job.id, after_seq=after_seq)
    body = "\n".join(event.to_ndjson() for event in events)
    return Response(content=body, media_type="application/x-ndjson")


@router.get("/accounts/{account_id}/draws")
def list_account_draws(account_id: str, limit: int = 50) -> List[dict]:
    _check_enabled()
    service = get_service()
    if service.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    return service.list_draws(account_id=account_id, limit=limit)


@router.get("/draws")
def list_draws(account_id: Optional[str] = None, limit: int = 50) -> List[dict]:
    _check_enabled()
    return get_service().list_draws(account_id=account_id, limit=limit)
