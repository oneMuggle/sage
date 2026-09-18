"""MCP OAuth 授权流纯函数库（切片 1，r60）。

完整授权链路（发现 → 注册 → 授权码流+PKCE → 回调 → token 存储/刷新 →
http_client 头注入）中的**无 I/O 地基**：PKCE 生成、发现 URL 构造、
元数据/回调/token 响应解析。仅依赖 stdlib（hashlib/base64/secrets/
urllib.parse），网络、存储与进程间回调由后续切片组合本模块实现。

规范依据：
- RFC 7636（PKCE）：verifier 43–128 字符非保留集；S256 challenge =
  BASE64URL(SHA256(ASCII(verifier))) 去填充。
- RFC 8414 §3（授权服务器元数据发现）：well-known 段插入 host 与
  path 之间。
- RFC 9728（受保护资源元数据）：同构插入。
- RFC 8707（resource 指示）：授权/令牌请求可选 resource 参数。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from backend.mcp.oauth_store import TokenRecord

__all__ = [
    "OAuthError",
    "OAuthMetadataError",
    "OAuthAuthorizeError",
    "OAuthStateError",
    "MIN_CODE_VERIFIER_LENGTH",
    "MAX_CODE_VERIFIER_LENGTH",
    "CODE_VERIFIER_CHARSET",
    "generate_code_verifier",
    "code_challenge_s256",
    "generate_pkce_pair",
    "generate_state",
    "build_authorization_server_discovery_urls",
    "build_protected_resource_discovery_urls",
    "parse_authorization_server_metadata",
    "parse_protected_resource_metadata",
    "build_authorization_url",
    "validate_authorization_callback",
    "parse_token_response",
    "is_token_expired",
    "build_refresh_request",
]


class OAuthError(RuntimeError):
    """OAuth 流程错误基类。"""


class OAuthMetadataError(OAuthError):
    """元数据 JSON 形状非法（缺必填字段/类型不符）。"""


class OAuthAuthorizeError(OAuthError):
    """授权端点返回 error（用户拒绝、client 无效等）。"""


class OAuthStateError(OAuthError):
    """回调 state 与发起时不匹配（CSRF 防护触发）。"""


MIN_CODE_VERIFIER_LENGTH = 43
MAX_CODE_VERIFIER_LENGTH = 128
#: RFC 7636 §4.1 unreserved charset
CODE_VERIFIER_CHARSET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def generate_code_verifier(length: int = 64) -> str:
    """生成 PKCE code_verifier（secrets 加密随机）。"""
    if not MIN_CODE_VERIFIER_LENGTH <= length <= MAX_CODE_VERIFIER_LENGTH:
        raise ValueError(
            f"code_verifier 长度必须在 {MIN_CODE_VERIFIER_LENGTH}–"
            f"{MAX_CODE_VERIFIER_LENGTH} 之间: {length}"
        )
    return "".join(secrets.choice(CODE_VERIFIER_CHARSET) for _ in range(length))


def code_challenge_s256(verifier: str) -> str:
    """S256 challenge：BASE64URL(SHA256(ASCII(verifier))) 去 '=' 填充。"""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_pkce_pair(length: int = 64) -> tuple:
    """返回 (code_verifier, code_challenge)。"""
    verifier = generate_code_verifier(length)
    return verifier, code_challenge_s256(verifier)


def generate_state() -> str:
    """CSRF state（32 字节 urlsafe 随机）。"""
    return secrets.token_urlsafe(32)


def _split_server_url(server_url: str) -> tuple:
    """拆 (scheme, netloc, path)；path 规范化为不带尾斜杠。"""
    parsed = urlparse(server_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"无效的 MCP server URL: {server_url}")
    return parsed.scheme, parsed.netloc, parsed.path.rstrip("/")


def build_authorization_server_discovery_urls(server_url: str) -> List[str]:
    """RFC 8414 §3 发现 URL 候选（well-known 插入 host 与 path 之间）。

    https://host/mcp      → [https://host/.well-known/oauth-authorization-server/mcp,
                              https://host/.well-known/oauth-authorization-server]
    https://host/a/b/mcp  → [https://host/.well-known/oauth-authorization-server/a/b/mcp,
                              https://host/.well-known/oauth-authorization-server/a/b,
                              ... 根]
    """
    scheme, netloc, path = _split_server_url(server_url)
    base = f"{scheme}://{netloc}/.well-known/oauth-authorization-server"
    urls: List[str] = []
    segments = [seg for seg in path.split("/") if seg]
    # path 逐级收敛：完整 path 插入形式 → 逐级父路径 → 根形式
    for i in range(len(segments), 0, -1):
        urls.append(f"{base}/{'/'.join(segments[:i])}")
    urls.append(base)
    return urls


def build_protected_resource_discovery_urls(server_url: str) -> List[str]:
    """RFC 9728 受保护资源元数据发现 URL 候选（同构插入）。"""
    scheme, netloc, path = _split_server_url(server_url)
    base = f"{scheme}://{netloc}/.well-known/oauth-protected-resource"
    urls: List[str] = []
    segments = [seg for seg in path.split("/") if seg]
    for i in range(len(segments), 0, -1):
        urls.append(f"{base}/{'/'.join(segments[:i])}")
    urls.append(base)
    return urls


def _require_str(data: dict, key: str, what: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OAuthMetadataError(f"{what} 缺少必填字符串字段: {key}")
    return value


def parse_authorization_server_metadata(data: object) -> Dict[str, object]:
    """校验并归一化 RFC 8414 授权服务器元数据。

    必填：issuer / authorization_endpoint / token_endpoint。
    其余字段（registration_endpoint、scopes_supported、
    token_endpoint_auth_methods 等）原样透传。
    """
    if not isinstance(data, dict):
        raise OAuthMetadataError("授权服务器元数据必须是 JSON 对象")
    meta: Dict[str, object] = dict(data)
    _require_str(meta, "issuer", "授权服务器元数据")
    _require_str(meta, "authorization_endpoint", "授权服务器元数据")
    _require_str(meta, "token_endpoint", "授权服务器元数据")
    return meta


def parse_protected_resource_metadata(data: object) -> Dict[str, object]:
    """校验并归一化 RFC 9728 受保护资源元数据。

    必填：resource；authorization_servers 应为字符串数组（缺失视为空）。
    """
    if not isinstance(data, dict):
        raise OAuthMetadataError("受保护资源元数据必须是 JSON 对象")
    meta: Dict[str, object] = dict(data)
    _require_str(meta, "resource", "受保护资源元数据")
    servers = meta.get("authorization_servers", [])
    if not isinstance(servers, list) or any(not isinstance(s, str) for s in servers):
        raise OAuthMetadataError("authorization_servers 必须是字符串数组")
    meta["authorization_servers"] = servers
    return meta


def build_authorization_url(
    authorization_endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: Optional[str] = None,
    resource: Optional[str] = None,
) -> str:
    """构造授权码流授权 URL（response_type=code + S256 PKCE）。"""
    if not authorization_endpoint:
        raise OAuthMetadataError("authorization_endpoint 不能为空")
    params: List[tuple] = [
        ("response_type", "code"),
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
        ("state", state),
        ("code_challenge", code_challenge),
        ("code_challenge_method", "S256"),
    ]
    if scope:
        params.append(("scope", scope))
    if resource:
        params.append(("resource", resource))
    sep = "&" if urlparse(authorization_endpoint).query else "?"
    return f"{authorization_endpoint}{sep}{urlencode(params)}"


def validate_authorization_callback(callback_url: str, expected_state: str) -> str:
    """校验授权回调：error 参数、state CSRF 校验；返回 authorization code。

    Raises:
        OAuthAuthorizeError: 回调携带 error（如 access_denied）。
        OAuthStateError: state 缺失或与发起时不一致。
    """
    query = parse_qs(urlparse(callback_url).query)
    if "error" in query:
        error = query["error"][0]
        description = query.get("error_description", [""])[0]
        raise OAuthAuthorizeError(f"{error}: {description}".strip(": ").strip())
    codes = query.get("code", [])
    if not codes:
        raise OAuthAuthorizeError("回调缺少 code 参数")
    states = query.get("state", [])
    if not states or states[0] != expected_state:
        raise OAuthStateError("回调 state 缺失或不匹配")
    return codes[0]


def parse_token_response(data: object) -> Dict[str, object]:
    """校验并归一化 token 端点成功响应（RFC 6749 §5.1）。

    access_token 必填；token_type 缺省 Bearer；expires_in 透传；
    refresh_token/scope 可选。
    """
    if not isinstance(data, dict):
        raise OAuthMetadataError("token 响应必须是 JSON 对象")
    token: Dict[str, object] = dict(data)
    _require_str(token, "access_token", "token 响应")
    token.setdefault("token_type", "Bearer")
    expires = token.get("expires_in")
    if expires is not None and (not isinstance(expires, int) or expires <= 0):
        raise OAuthMetadataError("expires_in 必须是正整数")
    return token


def is_token_expired(
    record: object,
    now: Optional[float] = None,
    skew_seconds: int = 60,
) -> bool:
    """判定 TokenRecord 是否已过期（expires_at=0 视为不过期）。

    skew_seconds 提前量：剩余寿命不足该值即视为过期，避免把"即将过期"
    的 token 注入请求后在途中失效。record 为 None 视为无 token（未过期
    无意义，调用方先判 None）；鸭子类型只读 expires_at，便于测试。
    """
    expires_at = float(getattr(record, "expires_at", 0.0) or 0.0)
    if expires_at <= 0:
        return False
    current = time.time() if now is None else float(now)
    return current >= expires_at - skew_seconds


def build_refresh_request(
    token_endpoint: str,
    client_id: str,
    refresh_token: str,
    scope: Optional[str] = None,
) -> tuple:
    """构造刷新请求（RFC 6749 §6）：(url, headers, form 编码 body)。

    token 端点要求 application/x-www-form-urlencoded。
    """
    if not token_endpoint:
        raise OAuthMetadataError("token_endpoint 不能为空")
    if not client_id:
        raise OAuthMetadataError("client_id 不能为空")
    if not refresh_token:
        raise OAuthMetadataError("refresh_token 不能为空")
    body: List[tuple] = [
        ("grant_type", "refresh_token"),
        ("refresh_token", refresh_token),
        ("client_id", client_id),
    ]
    if scope:
        body.append(("scope", scope))
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return token_endpoint, headers, urlencode(body)


# ---------- r62: 动态注册 + 授权码交换 + 授权编排（切片 3a） ----------


def build_dynamic_registration_request(
    client_name: str,
    redirect_uri: str,
    scope: Optional[str] = None,
) -> tuple:
    """RFC 7591 动态注册请求：(headers, JSON body dict)。

    Sage 是公共客户端（无后端密钥）：token_endpoint_auth_method=none，
    授权码 + PKCE + refresh 三 grant。
    """
    body: Dict[str, object] = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if scope:
        body["scope"] = scope
    headers = {"Content-Type": "application/json"}
    return headers, body


def parse_registration_response(data: object) -> Dict[str, object]:
    """校验 RFC 7591 注册响应：client_id 必填；secret 等可选透传。"""
    if not isinstance(data, dict):
        raise OAuthMetadataError("注册响应必须是 JSON 对象")
    reg: Dict[str, object] = dict(data)
    _require_str(reg, "client_id", "注册响应")
    return reg


def exchange_authorization_code(
    token_endpoint: str,
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_secret: Optional[str] = None,
    resource: Optional[str] = None,
) -> tuple:
    """授权码换 token（RFC 6749 §4.1.3 + PKCE verifier）：(url, headers, form body)。"""
    if not code:
        raise OAuthMetadataError("code 不能为空")
    if not redirect_uri:
        raise OAuthMetadataError("redirect_uri 不能为空")
    if not code_verifier:
        raise OAuthMetadataError("code_verifier 不能为空")
    body: List[tuple] = [
        ("grant_type", "authorization_code"),
        ("code", code),
        ("redirect_uri", redirect_uri),
        ("client_id", client_id),
        ("code_verifier", code_verifier),
    ]
    if client_secret:
        body.append(("client_secret", client_secret))
    if resource:
        body.append(("resource", resource))
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return token_endpoint, headers, urlencode(body)


async def authorize_mcp_server(
    server_url: str,
    *,
    redirect_uri: str,
    scope: Optional[str] = None,
    resource: Optional[str] = None,
    client_name: str = "sage",
    http_get_json: Any,
    http_post_json: Any,
    wait_for_callback: Any,
) -> TokenRecord:
    """完整授权编排：发现 → 动态注册 → 授权 → 回调校验 → code 交换。

    HTTP 与回调等待全部注入：
    - ``http_get_json(url) -> dict``：元数据发现（逐候选 URL 调用）；
    - ``http_post_json(url, headers, body) -> dict``：注册 + token 交换；
    - ``wait_for_callback(authorization_url) -> callback_url``：切片 3b
      提供本机回听；测试直传回调 URL。

    受保护资源元数据（RFC 9728）优先——携带 authorization_servers 时取
    第一个授权服务器；否则直接对 server_url 做授权服务器元数据发现。

    Returns:
        TokenRecord（client_id/token_endpoint 已回填，刷新链路即取即用）。
    """
    # 1) 发现：受保护资源 → 授权服务器（缺失/失败回退直查）
    auth_metadata: Optional[Dict[str, object]] = None
    issuer_fallback = None
    for url in build_protected_resource_discovery_urls(server_url):
        try:
            resource_meta = parse_protected_resource_metadata(await http_get_json(url))
        except Exception:
            continue
        servers = resource_meta.get("authorization_servers") or []
        if servers:
            issuer_fallback = str(servers[0])
            for candidate in build_authorization_server_discovery_urls(issuer_fallback):
                try:
                    auth_metadata = parse_authorization_server_metadata(
                        await http_get_json(candidate)
                    )
                    break
                except Exception:
                    continue
            if auth_metadata:
                break
    if auth_metadata is None:
        if issuer_fallback:
            candidates = build_authorization_server_discovery_urls(issuer_fallback)
        else:
            candidates = build_authorization_server_discovery_urls(server_url)
        for candidate in candidates:
            try:
                auth_metadata = parse_authorization_server_metadata(
                    await http_get_json(candidate)
                )
                break
            except Exception:
                continue
    if auth_metadata is None:
        raise OAuthMetadataError(f"无法发现 {server_url} 的 OAuth 元数据")

    issuer = str(auth_metadata.get("issuer", "")).rstrip("/")
    authorization_endpoint = str(auth_metadata["authorization_endpoint"])
    token_endpoint = str(auth_metadata["token_endpoint"])

    # 2) 动态注册（公共客户端）
    registration_endpoint = auth_metadata.get("registration_endpoint")
    if not isinstance(registration_endpoint, str) or not registration_endpoint:
        raise OAuthMetadataError(
            "授权服务器未提供 registration_endpoint（动态注册不可用）"
        )
    reg_headers, reg_body = build_dynamic_registration_request(
        client_name, redirect_uri, scope
    )
    registration = parse_registration_response(
        await http_post_json(registration_endpoint, reg_headers, reg_body)
    )
    client_id = str(registration["client_id"])

    # 3) 授权 URL → 回调 → 校验
    verifier, challenge = generate_pkce_pair()
    state = generate_state()
    authorization_url = build_authorization_url(
        authorization_endpoint,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
        scope=scope,
        resource=resource or (issuer or None),
    )
    callback_url = await wait_for_callback(authorization_url)
    code = validate_authorization_callback(callback_url, state)

    # 4) code 交换 → TokenRecord（client_id/token_endpoint 回填供刷新）
    url, headers, body = exchange_authorization_code(
        token_endpoint,
        client_id=client_id,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        resource=resource,
    )
    token = parse_token_response(await http_post_json(url, headers, body))
    expires_in = token.get("expires_in") or 0
    import time as _time

    return TokenRecord(
        server_name=server_url,
        access_token=str(token["access_token"]),
        token_type=str(token.get("token_type", "Bearer")),
        expires_at=float(_time.time()) + float(expires_in) if expires_in else 0.0,
        refresh_token=str(token.get("refresh_token") or ""),
        scope=str(token.get("scope") or (scope or "")),
        client_id=client_id,
        token_endpoint=token_endpoint,
    )
