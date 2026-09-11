# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""4 个期刊模板 LLM 工具（暴露 journal 子系统给 LLM 工具循环）。

- ``office_journal_parse_template``  (READ, requires_tool_context)
- ``office_journal_fill_from_content`` (WRITE_LOCAL, requires_tool_context)
- ``office_journal_generate_article`` (WRITE_LOCAL, requires_tool_context)
- ``office_journal_validate``         (READ, requires_tool_context)

所有工具走 ``_resolve_active_workspace`` 拿当前 chat session 绑定的工作区。
非绑定调用（无 ctx）→ 返 ``workspace_not_bound``。file_path 模式额外做
``_enforce_workspace`` 围栏（policy.workspace_root 非空时）。

LLM 代理桥接由 ``backend.office.journal.llm_adapter.JournalLLMAdapter`` 提供，
把 ``ProviderClient.complete`` 适配为 ``generate_article`` 期望的
``async generate(system_prompt=, user_prompt=, output_schema=) -> dict`` 接口。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from docx import Document

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.journal.errors import (
    JournalError,
    JournalSpecNotFoundError,
)
from backend.office.journal.generator import generate_article, generate_structured
from backend.office.journal.llm_adapter import get_default_journal_llm_adapter
from backend.office.journal.models import JournalContent, JournalSpec, parse_obj, to_jsonable
from backend.office.journal.parser import parse_journal_spec
from backend.office.journal.persistence import load_spec, save_spec
from backend.office.journal.validator import validate_document
from backend.office.session_workspace import get_active_workspace
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import ToolExecutionContext, current_tool_context

# ──────────────────────────────────────────────────────────────────────
# Workspace resolution helper
# ──────────────────────────────────────────────────────────────────────


def _resolve_active_workspace(
    ctx: Optional[ToolExecutionContext],
) -> Optional[Path]:
    """有活动绑定 → 绑定工作区 Path；否则 ``None``。

    与 office_template_tool 内的同名函数对齐签名。复用 ``get_active_workspace``
    走标准 binding 查询 + expected_generation 校验，防止 stale caller。
    """
    if ctx is None or not getattr(ctx, "session_id", None):
        return None
    try:
        conn = get_database().get_connection()
        binding = get_active_workspace(
            conn,
            ctx.session_id,
            expected_generation=ctx.binding_generation,
        )
    except Exception:  # noqa: BLE001 — DB 不可用时静默回 None
        return None
    if binding is None:
        return None
    return Path(binding.workspace_path)


def _resolve_spec(
    spec_id: Optional[str],
    file_path: Optional[str],
    workspace: Path,
) -> JournalSpec:
    """解析 spec 来源：spec_id → load_spec；file_path → parse_journal_spec。

    两者都给时优先 spec_id（更精确，避免重复解析）。
    """
    if isinstance(spec_id, str) and spec_id.strip():
        return load_spec(workspace, spec_id.strip())
    if isinstance(file_path, str) and file_path.strip():
        return parse_journal_spec(Path(file_path))
    raise JournalSpecNotFoundError("需要 spec_id 或 file_path")


# ──────────────────────────────────────────────────────────────────────
# Tool 1: parse_template
# ──────────────────────────────────────────────────────────────────────


class OfficeJournalParseTemplateTool(BaseTool):
    """从 .doc / .docx 模板抽取 JournalSpec。READ 工具。"""

    requires_tool_context = True
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_journal_parse_template",
            description=(
                "Parse a journal/academic template (.doc or .docx) and "
                "extract its JournalSpec: body/heading font, size, line "
                "spacing, margins, expected headings, citation style. Call "
                "before office_journal_fill_from_content or "
                "office_journal_generate_article. Result includes "
                "spec_id (cache key) and template_sha256."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the .doc / .docx template.",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(self, file_path: Optional[str] = None, **kwargs: Any) -> ToolResult:
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="content_shape_invalid")
        # 路径围栏：file_path 必须在绑定 workspace 内（policy.workspace_root）
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        p = Path(file_path).expanduser()
        if p.suffix.lower() not in {".doc", ".docx"}:
            return ToolResult(
                success=False,
                error="parse_failed: 仅支持 .doc / .docx",
            )
        try:
            spec = parse_journal_spec(p)
        except JournalError as exc:
            return ToolResult(success=False, error=f"parse_failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"parse_failed: {exc}")
        # 持久化到当前活动 workspace，让后续 fill/validate 工具能按 spec_id 命中。
        # 与 HTTP 路由层 parse-template 行为对齐（落 specs/<spec_id>.json + SQLite）。
        ws_path = _resolve_active_workspace(current_tool_context())
        if ws_path is not None:
            try:
                save_spec(ws_path, spec)
            except Exception as exc:  # noqa: BLE001
                # 持久化失败 → 不阻挡结果返回（parse 已经成功了），仅记日志。
                import logging

                logging.getLogger(__name__).warning(
                    "save_spec failed for %s: %s", spec.spec_id, exc
                )
        return ToolResult(
            success=True,
            content={"spec": to_jsonable(spec)},
        )


# ──────────────────────────────────────────────────────────────────────
# Tool 2: fill_from_content (structured fill, no LLM)
# ──────────────────────────────────────────────────────────────────────


class OfficeJournalFillFromContentTool(BaseTool):
    """结构化 fill 模式：把用户提供的 JournalContent 写入 docx 模板。WRITE_LOCAL 工具。"""

    requires_tool_context = True
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_journal_fill_from_content",
            description=(
                "Fill a journal template with structured content. Needs a "
                "spec_id (from previous office_journal_parse_template) or a "
                "file_path, and a 'content' dict with title/abstract/"
                "sections. Output is a filled .docx in the active workspace."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "spec_id": {
                        "type": "string",
                        "description": "spec_id from office_journal_parse_template.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Alternative: path to a .docx template.",
                    },
                    "content": {
                        "type": "object",
                        "description": (
                            "{title, abstract, sections: {keyword: text}, "
                            "references, citations}"
                        ),
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "Output filename (default: paper-<8 hex>.docx).",
                    },
                },
                "required": ["content"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        content: Optional[Dict[str, Any]] = None,
        spec_id: Optional[str] = None,
        file_path: Optional[str] = None,
        output_filename: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(content, dict):
            return ToolResult(success=False, error="content_shape_invalid")
        try:
            journal_content = parse_obj(JournalContent, content)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"content_shape_invalid: {exc}",
            )

        ctx = current_tool_context()
        workspace = _resolve_active_workspace(ctx)
        if workspace is None:
            return ToolResult(success=False, error="workspace_not_bound")

        try:
            spec = _resolve_spec(spec_id, file_path, workspace)
        except JournalError as exc:
            return ToolResult(success=False, error=f"spec_not_found: {exc}")

        filename = output_filename or f"paper-{uuid.uuid4().hex[:8]}.docx"
        try:
            record = generate_structured(spec, journal_content, workspace, filename)
        except JournalError as exc:
            error_code = "file_exists" if "exists" in str(exc).lower() else "output_path_invalid"
            return ToolResult(success=False, error=f"{error_code}: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"output_path_invalid: {exc}")
        return ToolResult(
            success=True,
            content={
                "gen_id": record.gen_id,
                "spec_id": record.spec_id,
                "output_path": record.output_path,
                "bytes": record.bytes_written,
            },
        )


# ──────────────────────────────────────────────────────────────────────
# Tool 3: generate_article (LLM self-correcting)
# ──────────────────────────────────────────────────────────────────────


class OfficeJournalGenerateArticleTool(BaseTool):
    """LLM 自纠生成模式：让 LLM 写满足 JournalSpec 的论文。WRITE_LOCAL 工具。

    走 ``JournalLLMAdapter``（桥接 ProviderClient），最多 max_rounds 轮自纠。
    """

    requires_tool_context = True
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_journal_generate_article",
            description=(
                "Generate a full article draft by having the LLM compose "
                "content that matches a JournalSpec, with up to 2 "
                "self-correction rounds. Uses office_journal_parse_template "
                "result as input. Slower than office_journal_fill_from_content "
                "but handles open-ended prompts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "spec_id": {"type": "string"},
                    "file_path": {"type": "string"},
                    "user_request": {
                        "type": "string",
                        "description": "User's high-level article request.",
                    },
                    "output_filename": {"type": "string"},
                    "max_rounds": {"type": "integer", "default": 2},
                },
                "required": ["user_request"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        user_request: Optional[str] = None,
        spec_id: Optional[str] = None,
        file_path: Optional[str] = None,
        output_filename: Optional[str] = None,
        max_rounds: int = 2,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(user_request, str) or not user_request.strip():
            return ToolResult(success=False, error="content_shape_invalid")
        ctx = current_tool_context()
        workspace = _resolve_active_workspace(ctx)
        if workspace is None:
            return ToolResult(success=False, error="workspace_not_bound")
        try:
            spec = _resolve_spec(spec_id, file_path, workspace)
        except JournalError as exc:
            return ToolResult(success=False, error=f"spec_not_found: {exc}")

        filename = output_filename or f"article-{uuid.uuid4().hex[:8]}.docx"

        # 适配器构造放 try 外 —— 失败属硬错（无 LLM provider），不允许走 fallback。
        try:
            adapter = get_default_journal_llm_adapter()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"parse_failed: LLM adapter unavailable — {exc}",
            )

        # 同步/异步协调：sync execute() 内调用 asyncio.run()/loop.run_until_complete；
        # 从已经运行的事件循环里调用（async chat loop）会失败并返清晰错误，
        # 不静默死锁。
        try:
            asyncio.get_running_loop()
            # 如果到达这里，说明已在 asyncio 事件循环内 — 不允许。
            return ToolResult(
                success=False,
                error=(
                    "output_path_invalid: generate_article must be called from the "
                    "synchronous tool loop, not an asyncio loop. Invoke via the LLM "
                    "tool dispatcher."
                ),
            )
        except RuntimeError:
            # 无运行中的事件循环 → 用 asyncio.run 创建新循环
            pass
        try:
            record = asyncio.run(
                generate_article(
                    spec, user_request=user_request, llm_proxy=adapter,
                    workspace=workspace, output_filename=filename,
                    max_rounds=max(1, int(max_rounds)),
                )
            )
        except JournalError as exc:
            error_code = "file_exists" if "exists" in str(exc).lower() else "output_path_invalid"
            return ToolResult(success=False, error=f"{error_code}: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"output_path_invalid: {exc}")

        return ToolResult(
            success=True,
            content={
                "gen_id": record.gen_id,
                "spec_id": record.spec_id,
                "output_path": record.output_path,
                "bytes": record.bytes_written,
                "llm_model": record.llm_model,
            },
        )


# ──────────────────────────────────────────────────────────────────────
# Tool 4: validate
# ──────────────────────────────────────────────────────────────────────


class OfficeJournalValidateTool(BaseTool):
    """校验成稿是否符合 JournalSpec。READ 工具。

    输入是已生成/已填好的 docx 文件路径（必填）；spec 通过 spec_id 或
    file_path（模板）解析。
    """

    requires_tool_context = True
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_journal_validate",
            description=(
                "Validate a filled .docx against a previously parsed "
                "JournalSpec. Returns violations (errors/warnings) with "
                "fix suggestions. Use after office_journal_fill_from_content "
                "or office_journal_generate_article."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "spec_id": {
                        "type": "string",
                        "description": "spec_id from office_journal_parse_template.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Absolute path to the filled .docx to validate "
                            "(required)."
                        ),
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(  # noqa: PLR0911 - many early-return guard clauses for input validation
        self,
        file_path: Optional[str] = None,
        spec_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="content_shape_invalid")
        # 路径围栏：被校验 docx 必须落在绑定工作区内
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        p = Path(file_path).expanduser()
        if not p.is_file():
            return ToolResult(
                success=False,
                error=f"parse_failed: file not found — {p}",
            )
        ctx = current_tool_context()
        workspace = _resolve_active_workspace(ctx)
        if workspace is None:
            return ToolResult(success=False, error="workspace_not_bound")
        try:
            spec = _resolve_spec(spec_id, None, workspace)
        except JournalError as exc:
            return ToolResult(success=False, error=f"spec_not_found: {exc}")
        try:
            doc = Document(str(p))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"parse_failed: {exc}")
        try:
            violations = validate_document(doc, spec)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"parse_failed: {exc}")
        return ToolResult(
            success=True,
            content={
                "spec_id": spec.spec_id,
                "file_path": str(p),
                "violations": [to_jsonable(v) for v in violations],
                "error_count": sum(1 for v in violations if v.severity.value == "error"),
                "warning_count": sum(
                    1 for v in violations if v.severity.value == "warning"
                ),
            },
        )


__all__ = [
    "OfficeJournalParseTemplateTool",
    "OfficeJournalFillFromContentTool",
    "OfficeJournalGenerateArticleTool",
    "OfficeJournalValidateTool",
]
