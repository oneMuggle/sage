"""M1.3 ``sage_doctor`` 工具 —— 把后端 doctor 的检查注册表暴露给 LLM。

复用 ``backend.cli.doctor`` 的检查注册表（``ALL_CHECKS`` / ``_run_one`` /
``_summarize`` / ``_import_all_checks``），跳过 ``run_doctor`` 子进程探测
（慢、且对 LLM 无意义 —— LLM 关心的是检查结果本身而非 probe 启动耗时）。

对应 Claude Code 的 ``/doctor`` 命令。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class SageDoctorTool(BaseTool):
    """运行 Sage 安装/环境检查（复用 doctor CLI 的检查注册表）。"""

    risk: RiskClass = RiskClass.READ

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="sage_doctor",
            description=(
                "运行 Sage 安装与环境自检（doctor 检查注册表），包括：Python/Node "
                "版本、conda 环境、数据库可写性、配置文件完整性、端口占用、LLM 配置、"
                "MCP 服务器状态、重型依赖、日志目录大小、网络策略、密钥存储、"
                "agent 档案文件结构、运行时环境等。结果按 CRITICAL/WARN/INFO 分级，"
                "附 fix_hint 修复建议。用于回答'Sage 环境哪里有问题'、'为什么 MCP "
                "连不上'、'密钥加密配置正确吗'等诊断类问题。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "include_subprocess_probe": {
                        "type": "boolean",
                        "description": (
                            "是否包含子进程启动探测（启动一次后端 Python 进程验证）。"
                            "默认 false（跳过，可省 5-10 秒）。仅在明确需要验证后端"
                            "启动链路时设为 true。"
                        ),
                        "default": False,
                    }
                },
            },
        )

    def execute(self, include_subprocess_probe: bool = False, **kwargs: Any) -> ToolResult:
        try:
            results, summary = self._run_checks(include_subprocess_probe)
        except Exception as exc:  # noqa: BLE001
            logger.exception("sage_doctor 执行失败")
            return ToolResult(
                success=False,
                error=f"doctor 执行失败: {exc}",
            )

        summary_text = self._build_summary_text(results, summary)
        return ToolResult(
            success=True,
            content={
                "checks": [r.to_dict() for r in results],
                "summary": summary,
            },
            output=summary_text,
        )

    @staticmethod
    def _run_checks(include_subprocess_probe: bool):
        from backend.cli.doctor import (
            ALL_CHECKS,
            _import_all_checks,
            _run_one,
            _summarize,
        )

        # 触发 @register 装饰器填充 ALL_CHECKS
        _import_all_checks()

        results = [_run_one(cls) for cls in ALL_CHECKS]

        # 子进程探测默认跳过（LLM 不需要，且耗时）
        if not include_subprocess_probe:
            results = [r for r in results if r.name != "backend_health"]

        summary = _summarize(results)
        return results, summary

    @staticmethod
    def _build_summary_text(results: list, summary: Dict[str, int]) -> str:
        lines: List[str] = []
        lines.append(
            f"Sage Doctor 完成: 共 {len(results)} 项检查 "
            f"(CRITICAL: {summary['critical']}, WARN: {summary['warn']}, "
            f"INFO: {summary['info']})"
        )
        # 优先展示 CRITICAL 和 WARN，INFO 只列名
        for r in results:
            if r.severity.value in {"critical", "warn"}:
                tag = f"[{r.severity.value.upper():>8}]"
                lines.append(f"{tag} {r.name:<22} {r.message}")
                if r.fix_hint:
                    lines.append(f"           fix: {r.fix_hint}")
        info_names = [r.name for r in results if r.severity.value == "info"]
        if info_names:
            lines.append(f"INFO 项 ({len(info_names)}): {', '.join(info_names)}")
        return "\n".join(lines)
