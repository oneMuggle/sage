"""profile_discover_backends 工具 —— 枚举站点可用文献库（spec §6.2）。

库清单必须在登录态下用浏览器抓取，因此本工具接受**快照文本**而不是自己
导航：模型用 browser_snapshot 拿到清单页快照后传给本工具，本工具负责解析、
与既有 backends 比对（**保留人工判定的 status**）、并写回 sidecar。

能力分类：WRITE_LOCAL（写用户目录下的 backends sidecar）。
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.literature.backends import parse_backend_entries
from backend.literature.knowledge import (
    merge_backends,
    read_sidecar,
    sidecar_path,
    write_sidecar,
)
from backend.literature.models import SiteBackend, parse_backends
from backend.literature.profile_store import user_sites_dir

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

PROFILE_DISCOVER_BACKENDS_TOOL_NAME = "profile_discover_backends"


class ProfileDiscoverBackendsTool(BaseTool):
    """枚举站点可用检索后端并写回 sidecar。"""

    risk = RiskClass.WRITE_LOCAL

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=PROFILE_DISCOVER_BACKENDS_TOOL_NAME,
            description=(
                "枚举站点可用的检索后端（文献库）。先用 browser_snapshot 拿到"
                "库清单页快照，再把快照文本传进来；本工具解析后与既有清单比对，"
                "保留人工判定的状态，写回 backends sidecar。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_id": {"type": "string", "description": "目标站点 id"},
                    "snapshot": {
                        "type": "string",
                        "description": "库清单页的快照文本",
                    },
                    "entry_url": {
                        "type": "string",
                        "description": "库清单页 URL（用于拼绝对地址）",
                    },
                    "backend_id": {
                        "type": "string",
                        "description": "只探测这一个后端（可选）",
                    },
                },
                "required": ["site_id", "snapshot"],
            },
        )

    def execute(
        self,
        site_id: str = "",
        snapshot: str = "",
        entry_url: str = "",
        backend_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """解析库清单并写回 backends sidecar。"""
        site = str(site_id or "").strip()
        if not site:
            return ToolResult(success=False, error="site_id 不能为空")
        if not str(snapshot or "").strip():
            return ToolResult(
                success=False,
                error="snapshot 不能为空（请先用 browser_snapshot 拿库清单页快照）",
            )

        target = sidecar_path(user_sites_dir(), site, "backends")
        existing_raw = read_sidecar(target)
        existing = parse_backends(existing_raw.get("backends"))
        existing_by_id = {backend.id: backend for backend in existing}

        discovered = parse_backend_entries(snapshot, entry_url or "https://")
        wanted = str(backend_id or "").strip()
        if wanted:
            discovered = [item for item in discovered if item.id == wanted]
        merged: List[SiteBackend] = []
        for backend in discovered:
            previous = existing_by_id.get(backend.id)
            if previous is not None:
                # 保留人工判定的 status / reason（spec §6.2）
                merged.append(previous)
            else:
                merged.append(backend)

        write_sidecar(
            target,
            {
                "backends": [
                    {
                        "id": backend.id,
                        "label": backend.label,
                        "entry_url": backend.entry_url,
                        "status": backend.status,
                        "reason": backend.reason,
                        "capabilities": dict(backend.capabilities),
                        "overrides": dict(backend.overrides),
                        "checked_at": backend.checked_at,
                    }
                    for backend in merge_backends(existing, merged)
                ]
            },
        )
        return ToolResult(
            success=True,
            content={
                "site_id": site,
                "discovered": [backend.id for backend in merged],
                "total": len(merged),
            },
        )
