"""profile_record_note 工具 —— 观测到经验的沉淀闭环（spec §7.1）。

把一次「非预期失败 + 已定位根因」写成一条结构化站点经验。经验落在
``~/.sage/literature_sites/<site_id>.notes.yaml``（sidecar），
**不触碰主 profile YAML** —— 用户的手写注释不能被机器写入毁掉。

能力分类：WRITE（本地文件副作用）。不涉及网络与外部服务。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.literature.knowledge import (
    merge_notes,
    read_sidecar,
    sidecar_path,
    write_sidecar,
)
from backend.literature.models import NOTE_SEVERITIES, SiteProfileError, parse_notes
from backend.literature.profile_store import user_sites_dir

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

PROFILE_RECORD_NOTE_TOOL_NAME = "profile_record_note"


class ProfileRecordNoteTool(BaseTool):
    """把一次失败沉淀成站点经验。"""

    risk = RiskClass.WRITE_LOCAL

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=PROFILE_RECORD_NOTE_TOOL_NAME,
            description=(
                "把一次已定位根因的失败记录为站点经验（写入 profile 的 notes sidecar）。"
                "下次运行时该经验会自动出现在检索指导文本里，避免重蹈覆辙。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_id": {"type": "string", "description": "目标站点 id"},
                    "note_id": {
                        "type": "string",
                        "description": "站点内唯一 slug（小写字母/数字/连字符）；同 id 覆盖",
                    },
                    "title": {"type": "string", "description": "一句话概括（≤60 字）"},
                    "symptom": {"type": "string", "description": "观察到的现象"},
                    "cause": {"type": "string", "description": "根因（未知可留空）"},
                    "workaround": {"type": "string", "description": "可执行的绕过/正确做法"},
                    "severity": {
                        "type": "string",
                        "enum": list(NOTE_SEVERITIES),
                        "description": "blocker（阻断）/ degraded（降级）/ cosmetic（提示）",
                    },
                    "applies_to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "作用面：search / pdf.entry / pdf.download / login / backend:<id>"
                        ),
                    },
                    "source_run": {"type": "string", "description": "来源运行目录名（可选）"},
                },
                "required": [
                    "site_id",
                    "note_id",
                    "title",
                    "symptom",
                    "workaround",
                    "severity",
                ],
            },
        )

    def execute(
        self,
        site_id: str = "",
        note_id: str = "",
        title: str = "",
        symptom: str = "",
        cause: str = "",
        workaround: str = "",
        severity: str = "degraded",
        applies_to: Optional[List[str]] = None,
        source_run: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """写入一条站点经验（sidecar，按 note_id 覆盖）。"""
        site = str(site_id or "").strip()
        if not site:
            return ToolResult(success=False, error="site_id 不能为空")

        payload: Dict[str, Any] = {
            "id": str(note_id or "").strip(),
            "title": str(title or "").strip(),
            "symptom": str(symptom or "").strip(),
            "cause": str(cause or "").strip(),
            "workaround": str(workaround or "").strip(),
            "severity": str(severity or "").strip(),
            "applies_to": [str(item) for item in (applies_to or [])],
            "learned_at": datetime.now(timezone.utc).date().isoformat(),  # noqa: UP017 — py38
            "verified_at": "",
            "source_run": str(source_run or "").strip(),
        }

        try:
            notes = parse_notes([payload])
        except SiteProfileError as exc:
            return ToolResult(success=False, error=f"invalid_note: {exc}")

        target = sidecar_path(user_sites_dir(), site, "notes")
        existing_raw = read_sidecar(target)
        existing = parse_notes(existing_raw.get("notes"))
        merged = merge_notes(existing, notes)
        write_sidecar(
            target,
            {
                "notes": [
                    {
                        "id": note.id,
                        "title": note.title,
                        "symptom": note.symptom,
                        "cause": note.cause,
                        "workaround": note.workaround,
                        "severity": note.severity,
                        "applies_to": list(note.applies_to),
                        "learned_at": note.learned_at,
                        "verified_at": note.verified_at,
                        "source_run": note.source_run,
                    }
                    for note in merged
                ]
            },
        )
        return ToolResult(
            success=True,
            content={"site_id": site, "note_id": notes[0].id, "total_notes": len(merged)},
        )
