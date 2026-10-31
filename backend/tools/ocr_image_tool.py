"""ocr_image 工具：读取工作区图片/聊天媒体并做本地 OCR（READ）。

用途：模型无法直接看图、或用户要求「只取文字」时，让 Agent 主动调用本地
OCR。仅读取工作区内文件或 MediaStore 媒体，不写文件；路径越界一律拒绝。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema, _is_safe_path
from backend.tools.context import current_tool_context

_MAX_TEXT_CHARS = 50_000


class OcrImageTool(BaseTool):
    """对本地图片/截图做 OCR，返回文本与行级置信度。"""

    requires_tool_context = True
    risk = RiskClass.READ
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="ocr_image",
            description=(
                "Run local OCR on an image/screenshot and return the recognized "
                "text. Use when the chat model cannot see images, or when the "
                "user asks to extract text only. Accepts a workspace-relative/"
                "absolute image path or a chat media_id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Image path inside the active chat workspace.",
                    },
                    "media_id": {
                        "type": "string",
                        "description": "Chat media id (alternative to path).",
                    },
                    "lang": {
                        "type": "string",
                        "enum": ["auto", "ch", "en"],
                        "description": "Recognition language; defaults to auto.",
                    },
                },
                "required": [],
            },
        )

    def execute(  # noqa: PLR0911 — 守卫链逐条 return 更直观
        self,
        path: Optional[str] = None,
        media_id: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not path and not media_id:
            return ToolResult(success=False, error="path_or_media_id_required")

        try:
            from backend.services.ocr import get_ocr_service

            service = get_ocr_service()
            if media_id:
                from backend.services.multimodal.media_store import MediaStore

                loaded = MediaStore().load(media_id)
                if loaded is None:
                    return ToolResult(success=False, error="media_not_found")
                _ref, content = loaded
                result = service.recognize_bytes(
                    content, source="media", lang=lang or "auto"
                )
            else:
                ctx = current_tool_context()
                if ctx is None:
                    return ToolResult(success=False, error="missing_tool_context")
                target = self._resolve_workspace_path(ctx, path or "")
                if target is None:
                    return ToolResult(success=False, error="path_outside_workspace")
                if not target.is_file():
                    return ToolResult(success=False, error="file_not_found")
                result = service.recognize_path(str(target), lang=lang or "auto")
        except Exception as exc:  # noqa: BLE001 — 工具边界统一折叠
            return ToolResult(success=False, error=f"ocr_failed: {exc}")

        if not result.ok:
            return ToolResult(success=False, error=result.error or "ocr_failed")

        content = result.to_dict()
        if len(content.get("text", "")) > _MAX_TEXT_CHARS:
            content["text"] = content["text"][:_MAX_TEXT_CHARS]
            content["truncated"] = True
        return ToolResult(success=True, content=content)

    def _resolve_workspace_path(self, ctx: Any, raw_path: str) -> Optional[Path]:
        """解析并校验工作区路径；无可用工作区时 fail-closed。"""
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
