"""
MCP tool wrapper — exposes MCP server tools as sage BaseTool instances.

M3: tools bind to the shared :class:`~backend.mcp.pool.McpServerPool`
(not a per-tool client), so reconnection and failure isolation are
centralized. Tool names are namespaced ``mcp__<server>__<tool>``
(pre-M3: ``<server>__<tool>`` — the ``mcp__`` prefix is an LLM-visible
change that disambiguates MCP tools from built-ins).
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

from backend.domain.media import RichMedia, media_envelope
from backend.mcp.client import McpClientError
from backend.mcp.pool import McpServerPool, get_pool, namespaced_tool_name
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class McpTool(BaseTool):
    """Wraps a single MCP server tool as a sage BaseTool.

    The MCP tool's inputSchema becomes the sage ToolSchema; execute()
    routes through the pool so a dead server yields a clean per-server
    error without affecting other servers' tools.
    """

    def __init__(self, pool: McpServerPool, server_name: str, tool_spec: Dict[str, Any]):
        """
        Args:
            pool: The shared MCP server pool (client lifecycle owner).
            server_name: Owning MCP server config name.
            tool_spec: Tool spec from MCP tools/list response
                       {"name": str, "description": str, "inputSchema": dict}
        """
        self._pool = pool
        self._server_name = server_name
        self._tool_spec = tool_spec
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        """Convert MCP tool spec to sage ToolSchema."""
        name = self._tool_spec["name"]
        description = self._tool_spec.get("description", "")
        input_schema = self._tool_spec.get("inputSchema", {})

        return ToolSchema(
            name=namespaced_tool_name(self._server_name, name),
            description=f"[MCP:{self._server_name}] {description}",
            parameters=input_schema,
        )

    def _persist_mcp_image(
        self,
        b64_data: str,
        image_format: str,
        mime_full: str,
        tool_name: str,
        store: Optional[Any] = None,
    ) -> Optional[RichMedia]:
        """Persist an inline MCP image to MediaStore, return a URL reference.

        Returns None on any failure so the caller can fall back to the legacy
        inline ``imageData`` path — a persistence hiccup must never drop the
        image from the assistant's reply.
        """
        try:
            from backend.services.multimodal.media_store import MediaKind, MediaStore

            raw = base64.b64decode(b64_data, validate=False)
            store = store or MediaStore()
            ref = store.save(
                raw,
                MediaKind.IMAGE,
                source=f"mcp:{self._server_name}",
                metadata={
                    "original_filename": f"{tool_name}.{image_format}",
                    "mime_type": mime_full,
                },
                ext=image_format,
            )
            return RichMedia(
                id=ref.id,
                kind="diagram" if image_format == "svg" else "image",
                mime_type=ref.mime_type,
                api_url=ref.api_url,
                format=image_format,
                title=tool_name,
                source=f"mcp:{self._server_name}",
                interactive=image_format == "svg",
            )
        except Exception as exc:  # noqa: BLE001 — persist failure must not lose the image
            logger.warning(
                "MCP image persist failed (server=%s tool=%s): %s",
                self._server_name,
                tool_name,
                exc,
            )
            return None

    def execute(self, **kwargs: Any) -> ToolResult:
        """Call the MCP tool via the pool and return the result."""
        mcp_tool_name = self._tool_spec["name"]

        try:
            response = self._pool.call_tool(self._server_name, mcp_tool_name, kwargs)
        except McpClientError as exc:
            logger.error(
                "MCP tool '%s' (server=%s) failed: %s",
                mcp_tool_name,
                self._server_name,
                exc,
            )
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — tool errors must not crash the agent
            logger.error(
                "Unexpected error calling MCP tool '%s' (server=%s): %s",
                mcp_tool_name,
                self._server_name,
                exc,
            )
            return ToolResult(
                success=False,
                error=f"MCP 服务器 {self._server_name} 不可用: {type(exc).__name__}: {exc}",
            )

        # Check for MCP-level error
        is_error = response.get("isError", False)

        # Extract content
        content_parts = response.get("content", [])
        text_parts = []
        media: List[RichMedia] = []
        metadata: Dict[str, Any] = {}

        for part in content_parts:
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif part.get("type") == "image":
                # MCP standard uses "mimeType", fall back to "format"
                raw_data = part.get("data", "")
                mime = part.get("mimeType") or part.get("format", "png")
                # Normalize mime type
                if mime == "image/svg+xml":
                    image_format = "svg"
                    mime_full = "image/svg+xml"
                elif mime == "image/png":
                    image_format = "png"
                    mime_full = "image/png"
                else:
                    image_format = "png"
                    mime_full = mime
                # A data URL prefix must be stripped before base64 decoding.
                b64_data = (
                    raw_data.split(",", 1)[1]
                    if raw_data.startswith("data:")
                    else raw_data
                )
                ref = self._persist_mcp_image(
                    b64_data, image_format, mime_full, mcp_tool_name
                )
                if ref is not None:
                    media.append(ref)
                    continue
                # Fallback: keep the inline data URL (legacy path).
                if raw_data.startswith("data:"):
                    metadata["imageData"] = raw_data
                else:
                    metadata["imageData"] = f"data:{mime_full};base64,{raw_data}"
                metadata["imageFormat"] = image_format

        # Also check for metadata at the response level
        if "metadata" in response:
            metadata.update(response["metadata"])

        text_output = "\n".join(text_parts) if text_parts else ""

        if is_error:
            error_content: Any = text_output
            if metadata:
                error_content = {"text": text_output, "metadata": metadata}
            return ToolResult(
                success=False,
                content=error_content,
                error=text_output or "MCP tool returned error",
            )

        # Persisted media wins; inline metadata only survives on fallback paths.
        if media:
            return ToolResult(
                success=True,
                content=media_envelope(
                    text_output, media, extra_metadata=metadata or None
                ),
            )

        result_content: Any = text_output
        if metadata:
            result_content = {"text": text_output, "metadata": metadata}

        return ToolResult(success=True, content=result_content)


def register_mcp_tools(registry: Any) -> None:
    """Track the registry, then start MCP discovery in the background.

    Startup must not block on MCP handshakes: first discovery runs on a daemon
    thread (``McpServerPool.start_background_discovery``). Servers that reach
    READY fan their tools into the tracked registry
    (``McpServerPool._register_server_tools``), so tools appear asynchronously
    without a restart — the same mechanism REST-added servers already use.
    """
    pool = get_pool()
    try:
        # Track first: discovery may already be running (or start concurrently)
        # and fan-out must reach this registry as servers settle.
        pool.track_registry(registry)
        pool.ensure_synced()
        pool.start_background_discovery()
        count = pool.register_tools_into(registry)
    except Exception as exc:  # noqa: BLE001 — MCP must never break startup
        logger.error("MCP tool registration failed: %s", exc)
        return
    if count:
        logger.info("Registered %d MCP tools into registry", count)
    else:
        logger.info("MCP tools: discovery running in background")


def shutdown_mcp_clients() -> None:
    """Stop all MCP server processes held by the global pool."""
    get_pool().shutdown_all()


class McpResourceTool(BaseTool):
    """L10 (批次 C-3): 读取 MCP 服务器资源的合成工具。

    spec 由 ``pool.synthesize_extra_specs`` 生成 (uri 枚举限定在
    resources/list 结果内), execute 走 pool.read_resource。
    """

    def __init__(self, pool: McpServerPool, server_name: str, tool_spec: Dict[str, Any]):
        self._pool = pool
        self._server_name = server_name
        self._tool_spec = tool_spec
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=namespaced_tool_name(self._server_name, self._tool_spec["name"]),
            description=f"[MCP:{self._server_name}] {self._tool_spec.get('description', '')}",
            parameters=self._tool_spec.get("inputSchema", {}),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        uri = str(kwargs.get("uri", ""))
        if not uri:
            return ToolResult(success=False, error="uri 必填")
        try:
            result = self._pool.read_resource(self._server_name, uri)
        except McpClientError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — 工具错误不崩溃 agent
            return ToolResult(success=False, error=f"读取资源失败: {exc}")
        contents = result.get("contents") if isinstance(result, dict) else None
        texts = [
            str(item.get("text", ""))
            for item in (contents or [])
            if isinstance(item, dict) and item.get("text") is not None
        ]
        return ToolResult(success=True, content={"uri": uri, "texts": texts})


def _render_prompt_result(result: Dict[str, Any]) -> str:
    """把 prompts/get 结果渲染为纯文本 (messages 列表)。"""
    parts = []
    for message in result.get("messages", []):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, dict):
            parts.append(str(content.get("text", "")))
        elif isinstance(content, list):
            parts.extend(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return "\n".join(part for part in parts if part)


class McpPromptTool(BaseTool):
    """L10 (批次 C-3): MCP prompt 模板的合成工具。

    execute → pool.get_prompt → 把模板消息渲染为纯文本返回。
    """

    def __init__(self, pool: McpServerPool, server_name: str, tool_spec: Dict[str, Any]):
        self._pool = pool
        self._server_name = server_name
        self._tool_spec = tool_spec
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=namespaced_tool_name(self._server_name, self._tool_spec["name"]),
            description=f"[MCP:{self._server_name}] {self._tool_spec.get('description', '')}",
            parameters={
                "type": "object",
                "properties": self._tool_spec.get("inputSchema", {}).get("properties", {}),
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        prompt_name = str(self._tool_spec.get("_sage_prompt_name", ""))
        if not prompt_name:
            return ToolResult(success=False, error="prompt name missing")
        try:
            result = self._pool.get_prompt(self._server_name, prompt_name, kwargs)
        except McpClientError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — 工具错误不崩溃 agent
            return ToolResult(success=False, error=f"获取 prompt 失败: {exc}")
        return ToolResult(success=True, content=_render_prompt_result(result if isinstance(result, dict) else {}))
