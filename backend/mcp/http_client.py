# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Streamable-HTTP MCP 传输客户端 (L10, 批次 C-3)。

与 stdio 版 :class:`~backend.mcp.client.McpClient` 同一鸭子类型接口
(``server_name / is_running / start / stop / list_tools / call_tool``)，
并扩展 ``list_resources / read_resource / list_prompts / get_prompt``。

协议口径 (MCP Streamable HTTP, 2025-03-26):
- 单一 endpoint, JSON-RPC 请求 POST;``Accept: application/json,
  text/event-stream``——服务器可能回 JSON 或 SSE, 两者都解析;
- 握手: ``initialize`` → 从响应头捕获 ``Mcp-Session-Id`` → 通知
  ``notifications/initialized`` (无 id, 无响应);
- 会话头随后续请求回传。

fail-fast 语义与 stdio 版一致: 通信失败抛 McpClientError。
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from typing import Any, Dict, List, Optional

import httpx

from backend.mcp.client import McpClientError
from backend.mcp.config import ServerConfig

logger = logging.getLogger(__name__)

#: 单请求 HTTP 超时下限（秒），防止配置成 0 卡死
_MIN_TIMEOUT = 1.0


class _SessionExpiredError(McpClientError):
    """The server rejected an established session (HTTP 404)."""


class HttpClientMcpClient:
    """Streamable-HTTP 传输的 MCP 客户端（同步接口）。"""

    def __init__(
        self,
        config: ServerConfig,
        http_client: Optional[httpx.Client] = None,
        oauth_store: Optional[object] = None,
    ):
        """``http_client`` 仅供测试注入 (httpx.MockTransport)。

        ``oauth_store``：OAuth token 存储句柄（r61 切片 2）；None →
        进程级单例。注入 fake store 便于测试。
        """
        self._config = config
        self._timeout = max(float(getattr(config, "timeout_seconds", 30.0) or 30.0), _MIN_TIMEOUT)
        self._url = getattr(config, "url", None) or ""
        if not self._url:
            raise McpClientError(f"MCP server '{config.name}' has no url for HTTP transport")
        self._session_id: Optional[str] = None
        self._started = False
        self._lock = threading.RLock()
        self._client = http_client
        # r61: OAuth token 存储（None → 进程级单例）；记录不存在 = 无 OAuth
        if oauth_store is None:
            from backend.mcp.oauth_store import get_oauth_token_store

            self._oauth_store = get_oauth_token_store()
        else:
            self._oauth_store = oauth_store

    # ---- 生命周期 ---------------------------------------------------------

    @property
    def server_name(self) -> str:
        return self._config.name

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> None:
        """initialize 握手 + initialized 通知。"""
        with self._lock:
            if self._started:
                return
            self._session_id = None
            result = self._post("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "sage", "version": "1.0"},
            }, expect_response=True)
            if not isinstance(result, dict) or not result:
                raise McpClientError(
                    f"MCP server '{self._config.name}': empty initialize response"
                )
            server_info = result.get("serverInfo") or {}
            logger.info(
                "[MCP-HTTP:%s] initialized: server=%s",
                self._config.name,
                server_info.get("name", "?"),
            )
            # initialized 通知 (无 id)
            self._post("notifications/initialized", {}, expect_response=False)
            self._started = True

    def stop(self) -> None:
        with self._lock:
            self._started = False
            self._session_id = None

    # ---- 工具 (与 stdio 版同接口) ----------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        result = self._request("tools/list", {}, expect_response=True)
        return result.get("tools", []) if isinstance(result, dict) else []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments}, expect_response=True
        )
        if not isinstance(result, dict):
            raise McpClientError(f"MCP server '{self._config.name}': malformed tools/call result")
        return result

    # ---- L10: resources / prompts ------------------------------------------

    def list_resources(self) -> List[Dict[str, Any]]:
        result = self._request("resources/list", {}, expect_response=True)
        return result.get("resources", []) if isinstance(result, dict) else []

    def read_resource(self, uri: str) -> Dict[str, Any]:
        result = self._request("resources/read", {"uri": uri}, expect_response=True)
        if not isinstance(result, dict):
            raise McpClientError(f"MCP server '{self._config.name}': malformed resources/read result")
        return result

    def list_prompts(self) -> List[Dict[str, Any]]:
        result = self._request("prompts/list", {}, expect_response=True)
        return result.get("prompts", []) if isinstance(result, dict) else []

    def get_prompt(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request(
            "prompts/get", {"name": name, "arguments": arguments}, expect_response=True
        )
        if not isinstance(result, dict):
            raise McpClientError(f"MCP server '{self._config.name}': malformed prompts/get result")
        return result

    # ---- 内部 ---------------------------------------------------------------

    def _oauth_authorization_header(self) -> Optional[str]:
        """从 token 存储解析 Authorization 头（r61）。

        过期且可刷新（refresh_token + client_id + token_endpoint 齐备）→
        同步刷新并回存；刷新失败 → 删除记录、按无 token 继续（fail-open，
        401 重授权属切片 3）。任何存储异常都不影响普通请求。
        """
        try:
            record = self._oauth_store.load(self._config.name)
        except Exception as exc:  # 存储故障不阻断请求
            logger.warning("[MCP-HTTP:%s] OAuth token 读取失败: %s", self._config.name, exc)
            return None
        if record is None:
            return None
        from backend.mcp.oauth import build_refresh_request, is_token_expired, parse_token_response

        if is_token_expired(record):
            if not (record.refresh_token and record.client_id and record.token_endpoint):
                return None
            try:
                url, req_headers, body = build_refresh_request(
                    record.token_endpoint, record.client_id, record.refresh_token, record.scope or None
                )
                client = self._client
                owned = False
                if client is None:
                    client = httpx.Client(timeout=self._timeout)
                    owned = True
                try:
                    resp = client.post(url, content=body, headers=req_headers)
                    resp.raise_for_status()
                finally:
                    if owned:
                        client.close()
                token = parse_token_response(json.loads(resp.text))
            except Exception as exc:
                logger.warning(
                    "[MCP-HTTP:%s] OAuth token 刷新失败，移除记录: %s", self._config.name, exc
                )
                with contextlib.suppress(Exception):
                    self._oauth_store.delete(self._config.name)
                return None
            import time as _time

            expires_in = token.get("expires_in") or 0
            record.access_token = str(token["access_token"])
            record.token_type = str(token.get("token_type", "Bearer"))
            record.expires_at = (
                float(_time.time()) + float(expires_in) if expires_in else 0.0
            )
            if isinstance(token.get("refresh_token"), str) and token["refresh_token"]:
                record.refresh_token = token["refresh_token"]
            try:
                self._oauth_store.save(record)
            except Exception as exc:
                logger.warning("[MCP-HTTP:%s] OAuth token 回存失败: %s", self._config.name, exc)
        return f"{record.token_type} {record.access_token}".strip()

    def _ensure_started(self) -> None:
        if not self._started:
            raise McpClientError(f"MCP server '{self._config.name}' is not started")

    def _request(self, method: str, params: Dict[str, Any], expect_response: bool) -> Any:
        # Serialize the session lifecycle with requests. Reconnect is bounded;
        # tools/call is NEVER replayed automatically (it may have side effects).
        with self._lock:
            self._ensure_started()
            try:
                return self._post(method, params, expect_response)
            except _SessionExpiredError as exc:
                self.start()
                if method == "tools/call":
                    raise McpClientError(
                        "MCP session expired and was renewed; tool call was not replayed. "
                        "Check its outcome before retrying."
                    ) from exc
                return self._post(method, params, expect_response)

    def _post(self, method: str, params: Dict[str, Any], expect_response: bool) -> Any:
        """POST 一条 JSON-RPC; 返回 result 字段或 None (通知/无响应)。"""
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if expect_response:
            payload["id"] = 1  # 单线程 + 串行锁, 固定 id 足够
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        # R34: 自定义鉴权头（如 Authorization: Bearer <PAT>）—— 配置即合并，
        # 每次请求携带；自定义头先合并，真实会话头后置优先（Mcp-Session-Id
        # 决定续连，不能被配置覆盖）。
        for h_key, h_value in (getattr(self._config, "headers", None) or {}).items():
            if (isinstance(h_key, str) and isinstance(h_value, str)
                    and h_key.lower() != "mcp-session-id"):
                headers[h_key] = h_value
        # r61: OAuth bearer token —— 在 config.headers 之后合并（覆盖静态
        # Authorization：授权动作晚于配置，新凭据优先）；无 token 记录时
        # 完全等价于现状。
        oauth_header = self._oauth_authorization_header()
        if oauth_header:
            headers["Authorization"] = oauth_header
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        client = self._client
        owned = False
        if client is None:
            client = httpx.Client(timeout=self._timeout)
            owned = True
        try:
            response = client.post(
                self._url,
                content=json.dumps(payload, ensure_ascii=False),
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            expired = (isinstance(exc, httpx.HTTPStatusError)
                       and exc.response.status_code == 404 and bool(self._session_id)
                       and method != "initialize")
            self._started = False
            self._session_id = None
            if expired:
                raise _SessionExpiredError("MCP HTTP session expired") from exc
            raise McpClientError(f"MCP HTTP error ({method}): {exc}") from exc
        finally:
            if owned:
                client.close()

        new_session = response.headers.get("mcp-session-id")
        if new_session:
            self._session_id = new_session

        if not expect_response:
            return None

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text, payload["id"])
        data = response.json()
        if "error" in data and data["error"]:
            raise McpClientError(f"MCP error ({method}): {data['error']}")
        return data.get("result")

    @staticmethod
    def _parse_sse(body: str, request_id: int) -> Any:
        """从 SSE 流中取与请求 id 匹配 (或最后一个) 的 JSON-RPC result。"""
        result: Any = None
        last_error: Optional[Dict[str, Any]] = None
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            try:
                data = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("id") == request_id:
                if data.get("error"):
                    last_error = data["error"]
                result = data.get("result")
        if result is None and last_error:
            raise McpClientError(f"MCP error: {last_error}")
        return result


__all__ = ["HttpClientMcpClient"]
