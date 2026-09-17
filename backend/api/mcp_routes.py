"""
MCP multi-server management REST API (M3).

Endpoints (mounted under ``/api/v1``):

- ``GET    /mcp/status``            — degraded-mode status report (always 200)
- ``GET    /mcp/servers``           — effective configs (env secrets redacted)
- ``POST   /mcp/servers``           — add user server + discover it
- ``PATCH  /mcp/servers/{name}``    — merge-patch enabled/timeout_seconds
- ``DELETE /mcp/servers/{name}``    — remove user entry (built-ins guarded)

pydantic models use the dual v1/v2 ``class Config`` style because the
release/win7 LTS branch pins pydantic 1.10 while main pins 2.x.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.mcp.client import McpClientError
from backend.mcp.config import McpConfigError, ServerConfig, validate_server_config
from backend.mcp.oauth_store import get_oauth_token_store
from backend.mcp.pool import McpServerPool, get_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

#: env keys containing any of these substrings (case-insensitive) are
#: redacted in GET responses — never echo secrets to the renderer.
#: Note "pat" also masks keys containing "path" (e.g. CHROME_PATH) —
#: acceptable: over-redaction of a non-secret beats leaking a PAT.
REDACT_KEY_MARKERS = (
    "key",
    "token",
    "secret",
    "password",
    "auth",
    "credential",
    "pat",
    "private",
)
REDACTED = "***"


# ---------- request / response models (pydantic v1/v2 dual-compat) ----------


class ServerConfigIn(BaseModel):
    """POST /mcp/servers body — full user server definition."""

    name: str = Field(min_length=1, max_length=64)
    command: str = Field(default="", max_length=512)
    url: Optional[str] = Field(default=None, max_length=2048)
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    # R34: HTTP 传输自定义鉴权头（stdio 服务器忽略）
    headers: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    required: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)

    class Config:
        extra = "forbid"


class ServerUpdateIn(BaseModel):
    """PATCH /mcp/servers/{name} body — merge-patch, all fields optional."""

    enabled: Optional[bool] = None
    timeout_seconds: Optional[float] = Field(default=None, gt=0, le=600)
    # R20-B: per-tool 级开关 —— 全量替换语义（传空数组 = 清空禁用清单）
    disabled_tools: Optional[List[str]] = None
    # R34: HTTP 鉴权头 —— 全量替换语义；GET 响应中按敏感键脱敏
    headers: Optional[Dict[str, str]] = None

    class Config:
        extra = "forbid"


# ---------- helpers -----------------------------------------------------------


def redact_env(env: Dict[str, str]) -> Dict[str, str]:
    """Mask env values whose key names look secret-bearing."""
    redacted: Dict[str, str] = {}
    for key, value in env.items():
        lowered = key.lower()
        if any(marker in lowered for marker in REDACT_KEY_MARKERS):
            redacted[key] = REDACTED
        else:
            redacted[key] = value
    return redacted


def _config_to_dict(config: ServerConfig, builtin: bool) -> Dict[str, Any]:
    data = config.to_dict()
    data["env"] = redact_env(config.env)
    # R34: 鉴权头与 env 同级敏感 —— Authorization/x-api-key 等值同样脱敏
    data["headers"] = redact_env(config.headers)
    # UI uses this to disable the delete button for built-in servers
    data["builtin"] = builtin
    return data


def _pool() -> McpServerPool:
    """Route entry: process-wide pool, lazily config-synced."""
    pool = get_pool()
    pool.ensure_synced()
    return pool


# ---------- routes ------------------------------------------------------------


@router.get("/mcp/status")
def mcp_status() -> Dict[str, Any]:
    """Status report across all configured servers. Always 200 — state
    travels in the body (degraded mode is not an HTTP error)."""
    report = _pool().status_report().to_dict()
    # r65: OAuth 授权状态可见化（不透出 token 本体）
    store = get_oauth_token_store()
    for entry in report.get("servers", []):
        if isinstance(entry, dict):
            entry["has_oauth_token"] = store.has(str(entry.get("name", "")))
    return report


@router.get("/mcp/servers")
def list_mcp_servers() -> Dict[str, Any]:
    """Effective (built-in + user merged) configs, env secrets redacted."""
    from backend.mcp.config import builtin_names

    pool = _pool()
    builtins = set(builtin_names())
    store = get_oauth_token_store()
    servers = []
    for c in pool.effective_configs():
        data = _config_to_dict(c, builtin=c.name in builtins)
        # r65: OAuth 授权状态可见化（不透出 token 本体）
        data["has_oauth_token"] = store.has(c.name)
        servers.append(data)
    return {"servers": servers}


@router.post("/mcp/servers")
def add_mcp_server(payload: ServerConfigIn) -> Dict[str, Any]:
    """Validate + persist a user server, then trigger discovery for it."""
    try:
        config = validate_server_config(
            name=payload.name,
            command=payload.command,
            url=payload.url,
            args=tuple(payload.args),
            env=dict(payload.env),
            enabled=payload.enabled,
            required=payload.required,
            timeout_seconds=payload.timeout_seconds,
            headers=dict(payload.headers),
        )
        record = _pool().add_server(config)
    except (McpConfigError, McpClientError) as exc:
        # Contract: 400 {"error": ...} for semantic validation failures
        # (schema-level violations arrive as FastAPI's standard 422).
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except OSError as exc:
        logger.error("MCP config persistence failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"config save failed: {exc}")
    return {"ok": True, "name": config.name, "state": record.state.value}


@router.patch("/mcp/servers/{name}")
def update_mcp_server(name: str, payload: ServerUpdateIn) -> Dict[str, Any]:
    """Merge-patch enabled/timeout_seconds; starts or stops the server.

    Timeout semantics: the response timeout is baked into a live client
    at construction, so changing ``timeout_seconds`` on a RUNNING server
    triggers a re-discovery (the server is briefly restarted) — the new
    value takes effect immediately instead of being silently ignored
    until the next natural reconnect.
    """
    pool = _pool()
    try:
        record = pool.update_server(
            name,
            enabled=payload.enabled,
            timeout_seconds=payload.timeout_seconds,
            disabled_tools=payload.disabled_tools,
            headers=payload.headers,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown MCP server: {name}")
    except McpConfigError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except OSError as exc:
        logger.error("MCP config persistence failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"config save failed: {exc}")
    return {"ok": True, "name": name, "state": record.state.value}


@router.get("/mcp/servers/{name}/tools")
def list_mcp_server_tools(name: str) -> Dict[str, Any]:
    """Per-tool management payload: sanitized specs + current disabled list.

    Read-only — never triggers discovery; a server that is not READY simply
    reports an empty tool list alongside its state. Only name + a truncated
    description are exposed (inputSchema never leaves the backend).
    """
    record = _pool().get_record(name)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown MCP server: {name}")
    tools = [
        {
            "name": str(spec.get("name", "")),
            "description": str(spec.get("description") or "")[:200],
        }
        for spec in record.tool_specs
        if isinstance(spec, dict) and spec.get("name")
    ]
    return {
        "server": name,
        "state": record.state.value,
        "tools": tools,
        "disabled_tools": list(record.config.disabled_tools),
    }


@router.post("/mcp/servers/{name}/authorize")
def authorize_mcp_server(name: str) -> Dict[str, Any]:
    """r64: HTTP 传输 MCP 服务器的 OAuth 授权收口（切片 1-3b 组合）。

    同步路由（线程池执行）——阻塞等待用户在浏览器完成登录属预期
    （上限 300s）。流程：loopback 回听拿 redirect_uri → webbrowser.open
    拉起授权页 → 回调捕获 → 动态注册 + code 交换 → TokenRecord 入库
    （切片 2 的 Authorization 注入/过期刷新即刻生效）。响应不回传
    token 本体。
    """
    import asyncio
    import time
    import webbrowser

    import httpx

    from backend.mcp.oauth_loopback import authorize_mcp_server_with_loopback
    from backend.mcp.oauth_store import get_oauth_token_store

    pool = _pool()
    config = next((c for c in pool.effective_configs() if c.name == name), None)
    if config is None:
        raise HTTPException(status_code=404, detail=f"unknown MCP server: {name}")
    if not config.url:
        return JSONResponse(
            status_code=400,
            content={"error": f"服务器 {name} 不是 HTTP 传输（stdio 无需 OAuth）"},
        )

    async def _get_json(url: str) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def _post_json(url: str, headers: Dict[str, str], body: Dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()

    started = time.time()
    try:
        record = asyncio.run(
            authorize_mcp_server_with_loopback(
                config.url,
                http_get_json=_get_json,
                http_post_json=_post_json,
                open_url=webbrowser.open,
                callback_timeout=300.0,
            )
        )
    except Exception as exc:
        logger.warning("[MCP:%s] OAuth 授权失败: %s", name, exc)
        return JSONResponse(status_code=400, content={"error": f"授权失败: {exc}"})

    record.server_name = name
    get_oauth_token_store().save(record)
    logger.info(
        "[MCP:%s] OAuth 授权完成 (%.0fs)", name, time.time() - started
    )
    return {
        "ok": True,
        "server": name,
        "token_type": record.token_type,
        "expires_at": record.expires_at,
    }


@router.delete("/mcp/servers/{name}")
def delete_mcp_server(name: str) -> Dict[str, Any]:
    """Remove a user server entry + unregister its tools.

    Built-in servers (drawio) without a user override cannot be deleted.
    """
    try:
        _pool().remove_server(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown MCP server: {name}")
    except McpClientError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except OSError as exc:
        logger.error("MCP config persistence failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"config save failed: {exc}")
    # r65: 删除服务器顺带清理 OAuth token（不留孤儿凭据）
    try:
        get_oauth_token_store().delete(name)
    except OSError as exc:
        logger.warning("[MCP:%s] OAuth token 清理失败: %s", name, exc)
    return {"ok": True, "name": name}
