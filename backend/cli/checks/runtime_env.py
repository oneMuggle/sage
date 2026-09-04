"""``runtime_env`` check —— 通过 runtime_probe 工具探测本机可用运行时。

设计:

- 复用 ``backend.tools.runtime_probe.RuntimeProbeTool``,不走 chat_service 链路
  (doctor CLI 在 CLI 进程内运行,无 chat_service 注入)。
- ``include_tools=False`` 只探语言运行时, 不附带 npm/pnpm/yarn —— doctor 不
  关心每个工具链是否存在, 用户可通过 Settings tab 或 runtime_probe API 看明细。
- 超时/失败 fail-open: doctor 单 check 抛异常 → WARN(RuntimeError: ...) →
  不会阻断 doctor 整体退出。

分级:
- CRITICAL: Python 完全不可用 (Sage 后端自身依赖 Python, 不可用 = 整体崩)
- WARN: Python 在但 Node.js 不可用 (Sage 自身不依赖 Node, 仅影响前端/JS 工具链)
- INFO: 全部可用
"""
from __future__ import annotations

import logging

from backend.cli.doctor import CheckResult, Severity, register
from backend.tools.runtime_probe import RuntimeProbeTool

logger = logging.getLogger(__name__)


@register
class RuntimeEnvCheck:
    name = "runtime_env"
    description = "探测本机可用编程语言运行时 (Python/Node.js)"

    def run(self) -> CheckResult:
        try:
            tool = RuntimeProbeTool()
            result = tool.execute(
                languages=["python", "javascript"],
                include_tools=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime_env check failed: %s", exc)
            return CheckResult(
                self.name,
                Severity.WARN,
                f"运行时探测失败: {exc}",
                "检查 backend.tools.runtime_probe 是否可正常 import",
            )

        if not result.success:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"runtime_probe 返回失败: {getattr(result, 'error', '未知错误')}",
            )

        content = result.content if isinstance(result.content, dict) else {}
        runtimes = content.get("runtimes") or []
        by_language: dict[str, int] = {}
        for r in runtimes:
            lang = r.get("language", "unknown")
            by_language[lang] = by_language.get(lang, 0) + 1

        py_count = by_language.get("python", 0)
        js_count = by_language.get("javascript", 0)
        summary = f"探测到 Python ×{py_count}, Node.js ×{js_count}"

        if py_count == 0:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"{summary} (Sage 后端依赖 Python, 必须可用)",
                "conda activate sage-backend 或安装 Python ≥3.10",
            )
        if js_count == 0:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"{summary} (前端/JS 工具链将不可用)",
                "安装 Node.js ≥18 (https://nodejs.org)",
            )
        return CheckResult(self.name, Severity.INFO, summary)
