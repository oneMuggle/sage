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


class HttpClientMcpClient:
    """Streamable-HTTP 传输的 MCP 客户端（同步接口）。"""

    def __init__(self, config: ServerConfig, http_client: Optional[httpx.Client] = None):
        """``http_client`` 仅供测试注入 (httpx.MockTransport)。"""
        self._config = config
        self._timeout = max(float(getattr(config, "timeout_seconds", 30.0) or 30.0), _MIN_TIMEOUT)
        self._url = getattr(config, "url", None) or ""
        if not self._url:
            raise McpClientError(f"MCP server '{config.name}' has no url for HTTP transport")
        self._session_id: Optional[str] = None
        self._started = False
        self._lock = threading.Lock()
        self._client = http_client

    # ---- 生命周期 ---------------------------------------------------------

    @property
    def server_name(self) -> str:
        return self._config.name

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> None:
        """initialize 握手 + initialized 通知。"""
        if self._started:
            return
        with self._lock:
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
        self._started = False

    # ---- 工具 (与 stdio 版同接口) ----------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        self._ensure_started()
        result = self._post("tools/list", {}, expect_response=True)
        return result.get("tools", []) if isinstance(result, dict) else []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_started()
        result = self._post(
            "tools/call", {"name": name, "arguments": arguments}, expect_response=True
        )
        if not isinstance(result, dict):
            raise McpClientError(f"MCP server '{self._config.name}': malformed tools/call result")
        return result

    # ---- L10: resources / prompts ------------------------------------------

    def list_resources(self) -> List[Dict[str, Any]]:
        self._ensure_started()
        result = self._post("resources/list", {}, expect_response=True)
        return result.get("resources", []) if isinstance(result, dict) else []

    def read_resource(self, uri: str) -> Dict[str, Any]:
        self._ensure_started()
        result = self._post("resources/read", {"uri": uri}, expect_response=True)
        if not isinstance(result, dict):
            raise McpClientError(f"MCP server '{self._config.name}': malformed resources/read result")
        return result

    def list_prompts(self) -> List[Dict[str, Any]]:
        self._ensure_started()
        result = self._post("prompts/list", {}, expect_response=True)
        return result.get("prompts", []) if isinstance(result, dict) else []

    def get_prompt(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_started()
        result = self._post(
            "prompts/get", {"name": name, "arguments": arguments}, expect_response=True
        )
        if not isinstance(result, dict):
            raise McpClientError(f"MCP server '{self._config.name}': malformed prompts/get result")
        return result

    # ---- 内部 ---------------------------------------------------------------

    def _ensure_started(self) -> None:
        if not self._started:
            raise McpClientError(f"MCP server '{self._config.name}' is not started")

    def _post(self, method: str, params: Dict[str, Any], expect_response: bool) -> Any:
        """POST 一条 JSON-RPC; 返回 result 字段或 None (通知/无响应)。"""
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if expect_response:
            payload["id"] = 1  # 单线程 + 串行锁, 固定 id 足够
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
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
