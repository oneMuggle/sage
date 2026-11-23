"""parse_document 工具：本地/内网 MinerU 可插拔解析（EXTERNAL）。

engine=auto 在本地文本质量低且 MinerU 已配置时，会把文档内容上传到内网
MinerU 服务；engine=local 保证文档绝不离机。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

from backend.domain.document_parse import ParseRequest, ParseResult
from backend.domain.risk import RiskClass
from backend.services.document_parse.factory import get_document_parse_service
from backend.tools.base import BaseTool, ToolResult, ToolSchema, _is_safe_path
from backend.tools.context import current_tool_context

_MAX_SOURCE_BYTES = 200 * 1024 * 1024


def _run_async(coro: Any) -> Any:
    """同步工具边界执行协程（有运行中事件循环时换新线程）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: List[Any] = []
    errors: List[BaseException] = []

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            box.append(loop.run_until_complete(coro))
        except BaseException as exc:  # noqa: BLE001 — 原样回抛给调用方
            errors.append(exc)
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, name="parse-document-bridge")
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return box[0]


def read_source_bytes(path: Optional[str], media_id: Optional[str]) -> Tuple[str, bytes]:
    """读取解析源：优先 media_id（聊天附件），其次已校验的工作区路径。"""
    if media_id:
        from backend.services.multimodal.media_store import MediaStore

        loaded = MediaStore().load(media_id)
        if loaded is None:
            raise FileNotFoundError("media_not_found")
        ref, content = loaded
        name = str(ref.metadata.get("original_filename") or (media_id + ".bin"))
        return name, content
    assert path is not None
    target = Path(path)
    if target.stat().st_size > _MAX_SOURCE_BYTES:
        raise ValueError("source_too_large")
    return target.name, target.read_bytes()


class ParseDocumentTool(BaseTool):
    requires_tool_context = True
    risk = RiskClass.EXTERNAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="parse_document",
            description=(
                "Parse a PDF/image/office document into text or structured output. "
                "The local engine runs on this machine; engine=mineru (or engine=auto "
                "when local text quality is low) uploads the document to the intranet "
                "MinerU server configured in Settings. Use engine=local to keep the "
                "document on-device."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Document path inside the active workspace.",
                    },
                    "media_id": {
                        "type": "string",
                        "description": "Chat media id (alternative to path).",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["auto", "local", "mineru"],
                        "description": "Parsing engine; defaults to auto.",
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["markdown", "structured", "docx", "html"],
                        "description": "Desired output; defaults to markdown.",
                    },
                    "pages": {
                        "type": "string",
                        "description": "PDF page range, e.g. '1-3' (MinerU only).",
                    },
                    "tier": {
                        "type": "string",
                        "enum": ["flash", "basic", "standard", "advanced"],
                        "description": "MinerU quality tier; defaults to the configured tier.",
                    },
                },
                "required": [],
            },
        )

    def execute(
        self,
        path: Optional[str] = None,
        media_id: Optional[str] = None,
        engine: Optional[str] = None,
        output_format: Optional[str] = None,
        pages: Optional[str] = None,
        tier: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not path and not media_id:
            return ToolResult(success=False, error="path_or_media_id_required")
        resolved_path = path
        if path and not media_id:
            ctx = current_tool_context()
            if ctx is None:
                return ToolResult(success=False, error="missing_tool_context")
            target = self._resolve_workspace_path(ctx, path)
            if target is None:
                return ToolResult(success=False, error="path_outside_workspace")
            if not target.is_file():
                return ToolResult(success=False, error="file_not_found")
            resolved_path = str(target)
        try:
            filename, content = read_source_bytes(resolved_path, media_id)
            request = ParseRequest(
                filename=filename,
                content_bytes=content,
                engine_hint=engine or "auto",
                output_format=output_format or "markdown",
                page_range=pages,
                tier=tier,
                source_path=resolved_path,
                media_id=media_id,
            )
            result: ParseResult = _run_async(
                get_document_parse_service().parse(request)
            )
        except Exception as exc:  # noqa: BLE001 — 工具边界统一折叠
            return ToolResult(success=False, error="parse_failed: " + str(exc))
        content_text = result.text
        if not content_text and result.media_url:
            content_text = "已生成文件：" + result.media_url
        return ToolResult(
            success=True,
            content=content_text,
            output={
                "engine_used": result.engine_used,
                "tier_used": result.tier_used,
                "quality_score": result.quality_score,
                "cached": result.cached,
                "duration_ms": result.duration_ms,
                "warnings": list(result.warnings),
                "media_url": result.media_url,
                "assets": dict(result.assets),
            },
        )

    def _resolve_workspace_path(self, ctx: Any, raw_path: str) -> Optional[Path]:
        """与 OcrImageTool 同款工作区解析（fail-closed）。"""
        if not raw_path:
            return None
        root: Optional[Path] = None
        policy_root = getattr(self._policy, "workspace_root", None)
        if policy_root:
            root = Path(policy_root).resolve()
        if root is None:
            try:
                from backend.data.database import get_database
                from backend.office.session_workspace import get_active_workspace

                conn = get_database().get_connection()
                binding = get_active_workspace(
                    conn,
                    ctx.session_id,
                    expected_generation=ctx.binding_generation,
                )
                if binding is not None:
                    root = Path(binding.workspace_path).resolve()
            except Exception:  # noqa: BLE001 — 无绑定按不可用处理
                root = None
        if root is None:
            return None
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not _is_safe_path(str(candidate), str(root)):
            return None
        return candidate
