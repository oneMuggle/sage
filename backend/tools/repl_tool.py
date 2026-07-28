"""
REPL 工具 - Python 代码片段隔离执行（移植 claw-code execute_repl）

- EXECUTE 能力：M1 权限执行器按模式矩阵门控（read_only 拒绝；
  workspace_write / prompt 逐次审批；full_access 放行；破坏性升级规则
  不适用——参数名是 ``code`` 而非 ``command``，bash 校验器天然跳过）。
- 子进程以隔离模式运行：``[sys.executable, "-I", "-c", code]``。
  ``-I`` 蕴含 ``-E``（忽略 PYTHON* 环境变量）、``-s``（忽略用户
  site-packages）、且不把脚本目录加入 sys.path——近似干净沙箱。
- 超时/启动失败 → ``success=False``；代码非零退出（含异常 traceback）
  → ``success=True`` 且 stdout/stderr 完整回传，让 agent 自己看栈。
- stdout/stderr 各截断到 100 KiB 上限。
- 子进程调用约定与 terminal.py 保持一致（subprocess.run + text=True +
  capture_output + timeout，不用 slots 等 3.8 以后特性）。
"""

import logging
import subprocess
import sys
import time
from typing import Tuple

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: 默认 / 上下限超时（秒）——LLM 传越界值时夹到区间内
REPL_DEFAULT_TIMEOUT_SECONDS = 30.0
REPL_MIN_TIMEOUT_SECONDS = 1.0
REPL_MAX_TIMEOUT_SECONDS = 120.0

#: stdout / stderr 各自的输出截断上限（100 KiB）
MAX_OUTPUT_BYTES = 100 * 1024


def clamp_timeout(value: float) -> float:
    """把超时夹到 [MIN, MAX] 区间。"""
    return min(max(float(value), REPL_MIN_TIMEOUT_SECONDS), REPL_MAX_TIMEOUT_SECONDS)


def _cap_output(text: str) -> Tuple[str, bool]:
    """按 UTF-8 字节数截断输出到 100 KiB；返回 (文本, 是否截断)。"""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return text, False
    capped = encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    return f"{capped}\n...[输出超过 100 KiB 上限，已截断]", True


class ReplTool(BaseTool):
    """REPL 工具 - 在隔离子进程中执行 Python 片段"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="repl",
            description=(
                "在隔离 Python 子进程中执行代码片段并返回 stdout/stderr/exit_code。"
                "适合快速数值验证、数据处理试验、算法草稿。"
                "代码以 python -I（隔离模式）运行；非零退出仍返回执行结果（含 traceback）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的 Python 源代码"},
                    "timeout": {
                        "type": "number",
                        "description": (
                            f"超时秒数 (默认 {REPL_DEFAULT_TIMEOUT_SECONDS:.0f}，"
                            f"上限 {REPL_MAX_TIMEOUT_SECONDS:.0f})"
                        ),
                    },
                },
                "required": ["code"],
            },
        )

    def execute(self, code: str = "", timeout: float = REPL_DEFAULT_TIMEOUT_SECONDS, **kwargs) -> ToolResult:
        """
        执行 Python 代码片段

        Args:
            code:    Python 源代码
            timeout: 超时秒数（越界夹到 [1, 120]）

        Returns:
            ToolResult；content 含 exit_code / stdout / stderr /
            duration_seconds / truncated。超时或进程启动失败 →
            success=False；代码非零退出 → success=True。
        """
        if not isinstance(code, str) or not code.strip():
            return ToolResult(success=False, error="code 不能为空")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
            return ToolResult(success=False, error="timeout 必须是数字")

        effective_timeout = clamp_timeout(timeout)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", code],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"REPL 执行超时（{effective_timeout:g} 秒），子进程已被终止",
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"REPL 子进程启动失败: {exc}")
        except Exception as exc:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("repl 执行失败: %s", exc)
            return ToolResult(success=False, error=f"REPL 执行错误: {exc}")

        duration = time.monotonic() - started
        stdout, stdout_truncated = _cap_output(completed.stdout or "")
        stderr, stderr_truncated = _cap_output(completed.stderr or "")

        # 非零退出（含未捕获异常）仍是"成功执行了一次"：agent 需要看到
        # traceback 自行纠错，因此 success=True + 完整结果。
        return ToolResult(
            success=True,
            content={
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_seconds": round(duration, 3),
                "truncated": stdout_truncated or stderr_truncated,
            },
        )
