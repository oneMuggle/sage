"""``project_diagnose`` 工具 — 评估当前项目环境满足度。

只读分析项目清单与运行时，输出满足 / 部分满足 / 不满足诊断。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.runtime import (
    Diagnostic,
    DiagnosticLevel,
    DiagnosticSeverity,
    ProbeRequest,
    ProjectDiagnosis,
    ProjectManifest,
    RuntimeInfo,
)
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.runtime_adapter import AdapterContext, registry
from backend.tools.runtime_safe_run import safe_run

logger = logging.getLogger(__name__)


class ProjectDiagnoseTool(BaseTool):
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="project_diagnose",
            description=(
                "识别当前目录项目类型（Python / Node.js / TypeScript 等），"
                "对比已知运行时，输出满足 / 部分满足 / 不满足诊断与修复建议。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选：仅诊断这些语言；空表示全部已注册适配器",
                    },
                    "include_tools": {
                        "type": "boolean",
                        "description": "同时探测工具链（如 npm/pnpm/yarn）",
                        "default": True,
                    },
                    "target_version": {
                        "type": "string",
                        "description": "可选的最低版本约束",
                    },
                    "project_root": {
                        "type": "string",
                        "description": "项目根目录；默认使用当前工作目录",
                    },
                },
            },
        )

    def execute(  # type: ignore[override]
        self,
        *,
        languages: Optional[List[str]] = None,
        include_tools: bool = True,
        target_version: Optional[str] = None,
        project_root: Optional[str] = None,
        **_kwargs: Any,
    ) -> ToolResult:
        root = Path(project_root) if project_root else Path.cwd()
        ctx = AdapterContext(workspace_root=root, safe_run=safe_run)

        request = ProbeRequest(
            languages=tuple(languages or ()),
            include_tools=include_tools,
            target_version=target_version,
        )
        target_adapter_languages = (
            list(request.languages) if request.languages else registry.languages()
        )
        all_runtimes: List[RuntimeInfo] = []
        probe_errors: List[str] = []
        for lang in target_adapter_languages:
            adapter = registry.get(lang)
            if adapter is None:
                probe_errors.append(f"未注册的运行时语言: {lang}")
                continue
            try:
                all_runtimes.extend(adapter.discover(request, ctx))
            except Exception as exc:  # noqa: BLE001
                logger.warning("project_diagnose discover %s 失败: %s", lang, exc)
                probe_errors.append(f"{lang}: {exc}")

        per_language: Dict[str, ProjectDiagnosis] = {}
        manifests: List[ProjectManifest] = []
        diagnostics: List[Diagnostic] = []
        for lang in registry.languages():
            adapter = registry.get(lang)
            if adapter is None:
                continue
            try:
                diagnosis = adapter.diagnose(root, all_runtimes, ctx)
            except Exception as exc:  # noqa: BLE001
                logger.warning("project_diagnose %s 失败: %s", lang, exc)
                diagnostics.append(
                    Diagnostic(
                        code="DIAGNOSE_INTERNAL_ERROR",
                        severity=DiagnosticSeverity.WARNING,
                        message=f"{lang} 诊断失败: {exc}",
                    )
                )
                continue
            per_language[lang] = diagnosis
            manifests.extend(diagnosis.manifests)
            diagnostics.extend(diagnosis.diagnostics)

        level = DiagnosticLevel.SATISFIED
        for diag in per_language.values():
            if diag.level is DiagnosticLevel.UNSATISFIED:
                level = DiagnosticLevel.UNSATISFIED
                break
            if diag.level is DiagnosticLevel.PARTIAL and level is DiagnosticLevel.SATISFIED:
                level = DiagnosticLevel.PARTIAL

        recommended: Optional[str] = None
        for diag in per_language.values():
            if diag.recommended_runtime:
                recommended = diag.recommended_runtime
                break
        if not recommended:
            for r in all_runtimes:
                if r.is_default:
                    recommended = r.path
                    break
        if not recommended and all_runtimes:
            for r in all_runtimes:
                if r.capabilities.can_execute and r.is_compatible is not False:
                    recommended = r.path
                    break

        result = ProjectDiagnosis(
            level=level,
            diagnostics=diagnostics,
            manifests=manifests,
            recommended_runtime=recommended,
        )
        return ToolResult(
            success=True,
            content={**result.to_dict(), "probe_errors": probe_errors},
        )


__all__ = ["ProjectDiagnoseTool"]
