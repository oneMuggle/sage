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
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

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
