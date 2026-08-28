"""
REPL 工具 - Python 代码片段隔离执行（移植 claw-code execute_repl）

- EXECUTE 能力：M1 权限执行器按模式矩阵门控（read_only 拒绝；
  workspace_write / prompt 逐次审批；full_access 放行；破坏性升级规则
  不适用——参数名是 ``code`` 而非 ``command``，bash 校验器天然跳过）。
- 子进程以隔离模式运行：``[sys.executable, "-I", <临时脚本>]``。
  ``-I`` 蕴含 ``-E``（忽略 PYTHON* 环境变量）、``-s``（忽略用户
  site-packages）、且不把脚本目录加入 sys.path——近似干净沙箱。
- 代码经临时 ``.py`` 文件传递而非 ``-c`` argv：Windows CreateProcess
  命令行有 32 767 字符硬上限，大片段走 argv 会直接失败；临时文件无此
  限制（执行完毕后删除）。
- 子进程 stdout/stderr 重定向到临时文件，进程结束后**只读前 100 KiB**：
  片段打印几个 GB 也不会撑爆父进程内存（磁盘暴露面 = 片段输出体积，
  可接受的取舍——比在父进程 PIPE 里无限缓冲安全得多）。
- 超时杀**整个进程组**而非单个子进程：POSIX 下 ``start_new_session=True``
  开新会话/进程组，``os.killpg`` 连孙进程一起收掉；Windows 下
  ``start_new_session=True`` 映射 ``CREATE_NEW_PROCESS_GROUP``，退化用
  ``p.kill()`` 尽力杀（杀不到孙进程，已知限制）。``start_new_session``
  是 Python 3.2+ 关键字参数，Win7 安全。
- 超时/启动失败 → ``success=False``；代码非零退出（含异常 traceback）
  → ``success=True`` 且 stdout/stderr 完整回传，让 agent 自己看栈。
- stdout/stderr 各截断到 100 KiB 上限。
"""

import logging
import subprocess
import sys
import tempfile
import time
from typing import Tuple

from .base import BaseTool, ToolResult, ToolSchema
from .subprocess_util import (
    kill_process_tree,
    make_temp_output_file,
    read_capped_output,
    unlink_quietly,
)

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


def _write_temp_script(code: str) -> str:
    """把代码写入临时 ``.py`` 脚本，返回路径（调用方负责删除）。

    规避 Windows ``-c`` argv 的 32 767 字符 CreateProcess 上限；
    ``delete=False`` + 先 close 保证 Windows 上子进程能再打开该文件。
    """
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        prefix="sage_repl_",
        suffix=".py",
        encoding="utf-8",
        delete=False,
    )
    try:
        handle.write(code)
    finally:
        handle.close()
    return handle.name


def _make_temp_output_file() -> str:
    """建一个承接子进程输出的空临时文件（repl 前缀）。"""
    return make_temp_output_file(prefix="sage_repl_")


def _read_capped_output(file_path: str) -> Tuple[str, bool]:
    """读输出文件前 ``MAX_OUTPUT_BYTES`` 字节；返回 (文本, 是否截断)。"""
    text, truncated, _offset = read_capped_output(file_path, cap=MAX_OUTPUT_BYTES)
    return text, truncated


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

    def execute(
        self, code: str = "", timeout: float = REPL_DEFAULT_TIMEOUT_SECONDS, **kwargs
    ) -> ToolResult:
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
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(
                success=False,
                error=f"未知参数: {names}（合法参数: code, timeout）",
            )
        if not isinstance(code, str) or not code.strip():
            return ToolResult(success=False, error="code 不能为空")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
            return ToolResult(success=False, error="timeout 必须是数字")

        effective_timeout = clamp_timeout(timeout)
        script_path = None
        stdout_path = None
        stderr_path = None
        try:
            script_path = _write_temp_script(code)
            stdout_path = _make_temp_output_file()
            stderr_path = _make_temp_output_file()
            return self._run_subprocess(
                script_path, stdout_path, stderr_path, effective_timeout
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"REPL 子进程启动失败: {exc}")
        except Exception as exc:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("repl 执行失败: %s", exc)
            return ToolResult(success=False, error=f"REPL 执行错误: {exc}")
        finally:
            for path in (script_path, stdout_path, stderr_path):
                if path is not None:
                    unlink_quietly(path)

    def _run_subprocess(
        self,
        script_path: str,
        stdout_path: str,
        stderr_path: str,
        effective_timeout: float,
    ) -> ToolResult:
        """Popen + communicate(timeout) 主流程；杀进程路径由本方法独占。"""
        started = time.monotonic()
        # 刻意不用 with：句柄要跨越 Popen 存活，由下方 finally 统一关闭
        out_handle = open(stdout_path, "wb")  # noqa: SIM115
        err_handle = open(stderr_path, "wb")  # noqa: SIM115
        try:
            # start_new_session: POSIX → 新会话+新进程组（超时 killpg 连孙进程
            # 一起杀）；Windows → CREATE_NEW_PROCESS_GROUP（杀进程组退化为
            # p.kill() 尽力杀，见共享 subprocess_util）
            process = subprocess.Popen(
                [sys.executable, "-I", script_path],
                stdin=subprocess.DEVNULL,
                stdout=out_handle,
                stderr=err_handle,
                start_new_session=True,
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"REPL 子进程启动失败: {exc}")
        finally:
            # 子进程已继承 fd，父进程的句柄启动后即可关闭（成败都要关）
            out_handle.close()
            err_handle.close()

        timed_out = False
        try:
            # stdout/stderr 都重定向到文件 → communicate 返回 (None, None)，
            # 只借它做"等待 + 超时"语义；退出码走 process.returncode
            process.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_tree(process)

        duration = time.monotonic() - started
        if timed_out:
            return ToolResult(
                success=False,
                error=f"REPL 执行超时（{effective_timeout:g} 秒），子进程已被终止",
            )

        stdout, stdout_truncated = _read_capped_output(stdout_path)
        stderr, stderr_truncated = _read_capped_output(stderr_path)

        # 非零退出（含未捕获异常）仍是"成功执行了一次"：agent 需要看到
        # traceback 自行纠错，因此 success=True + 完整结果。
        return ToolResult(
            success=True,
            content={
                "exit_code": process.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_seconds": round(duration, 3),
                "truncated": stdout_truncated or stderr_truncated,
            },
        )
