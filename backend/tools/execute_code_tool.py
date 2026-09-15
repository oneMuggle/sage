"""ExecuteCode Tool - 零上下文工具调用 (Round 8, 对标 hermes execute_code / RPC)

Agent 在子进程中执行一段 Python 代码；代码内通过 ``sage.call(tool_name,
**arguments)`` 回调父进程的工具注册表 —— **N 次工具调用只占一次 LLM
往返的上下文**（对比逐次工具调用每次都要完整走一遍请求/响应）。
适合批量文件处理、数据分析、多步机械操作等"脚本内循环"场景。

安全模型（与 repl/bash 同级）:
- 子进程 ``python -I`` 隔离 import/环境；**不是 OS 沙箱**（文件系统、
  网络、子进程不隔离）—— 权限面与 bash 工具等同，走 EXEC 风险类 +
  权限执行器审批。
- RPC 协议: JSON 行（子进程 stdout 打 ``##RPC##`` 前缀行，用户 print
  重定向到 stderr）；父进程逐行响应，整体 deadline 到期 kill 子进程。
- 单条 RPC 调用失败以 RuntimeError 抛回脚本内，由 agent 代码自行处理。
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

DEFAULT_CODE_TIMEOUT_SECONDS = 60.0
MAX_CODE_TIMEOUT_SECONDS = 300.0
MAX_CODE_BYTES = 64 * 1024
RPC_PREFIX = "##RPC##"
_MAX_OUTPUT_CHARS = 30000


def _bootstrap_script() -> str:
    """子进程引导：用户 print → stderr，协议行（带 RPC_PREFIX）走真实 stdout，
    注入 sage 对象；末尾由 _runner_script 执行用户代码并发 done 行"""
    return (
        "import sys, json, traceback\n"
        "_PROTO = sys.__stdout__\n"
        "# Windows 管道默认 locale 编码(gbk)，与父进程 utf-8 解码不匹配;\n"
        "# -I 模式忽略 PYTHONIOENCODING，必须显式 reconfigure。\n"
        "try:\n"
        "    _PROTO.reconfigure(encoding='utf-8')\n"
        "    sys.stderr.reconfigure(encoding='utf-8')\n"
        "except Exception:\n"
        "    pass\n"
        "class _ToStderr:\n"
        "    def write(self, s):\n"
        "        try:\n"
        "            sys.stderr.write(s)\n"
        "        except Exception:\n"
        "            pass\n"
        "    def flush(self):\n"
        "        try:\n"
        "            sys.stderr.flush()\n"
        "        except Exception:\n"
        "            pass\n"
        "sys.stdout = _ToStderr()\n"
        "_rid = [0]\n"
        "class SageBridge:\n"
        '    """父进程工具注册表的 RPC 桥（一次调用 = 一次工具执行）"""\n'
        "    def call(self, name, **arguments):\n"
        "        _rid[0] += 1\n"
        "        _PROTO.write("
        + repr(RPC_PREFIX)
        + " + json.dumps({'type': 'call', 'id': _rid[0], 'name': name, "
        "'arguments': arguments}, ensure_ascii=False) + '\\n')\n"
        "        _PROTO.flush()\n"
        "        line = sys.stdin.readline()\n"
        "        if not line:\n"
        "            raise RuntimeError('RPC bridge closed')\n"
        "        resp = json.loads(line)\n"
        "        if not resp.get('ok'):\n"
        "            raise RuntimeError(str(resp.get('error')))\n"
        "        return resp.get('value')\n"
        "sage = SageBridge()\n"
        "def _emit_done(payload):\n"
        "    _PROTO.write("
        + repr(RPC_PREFIX)
        + " + json.dumps(payload, ensure_ascii=False) + '\\n')\n"
        "    _PROTO.flush()\n"
    )


def _runner_script(user_code: str) -> str:
    """包裹用户代码：exec + done 行（成功/异常都回传）"""
    return (
        "_USER_CODE = "
        + repr(user_code)
        + "\n"
        + "try:\n"
        + "    exec(compile(_USER_CODE, '<user_code>', 'exec'), {'sage': sage})\n"
        + "    _emit_done({'type': 'done', 'ok': True, 'value': None})\n"
        + "except BaseException as exc:\n"
        + "    _emit_done({'type': 'done', 'ok': False, 'error': repr(exc),\n"
        + "                'traceback': traceback.format_exc()})\n"
    )


class ExecuteCodeTool(BaseTool):
    """零上下文工具调用 —— 子进程执行代码，sage.call() RPC 回注册表"""

    is_blocking = True

    # EXEC 风险类 —— 子进程可执行任意代码，权限面与 bash 等同
    # （base.py 注释: 新增工具务必声明 risk，并同步扩充 test_risk.py 验收表）
    risk = RiskClass.EXEC

    def __init__(self, registry: Any, policy: Any = None) -> None:
        super().__init__(policy=policy)
        self._registry = registry  # ToolRegistry（register_all_tools 注入）

    def _get_registry(self) -> Any:
        if self._registry is None:
            raise RuntimeError("execute_code: 工具注册表未注入")
        return self._registry

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="execute_code",
            description=(
                "在隔离子进程中执行 Python 代码，并通过 sage.call(tool_name, "
                "**args) 直接调用其它工具 —— N 次工具调用只占一次往返，"
                "适合批量文件处理、数据分析、多步机械操作。"
                "可用工具名单见各工具的 schema。python -I 隔离 import 与"
                " Python 环境；不是 OS 沙箱。整体有超时上限。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "要执行的 Python 源代码；用 sage.call(name, "
                            "**args) 调用工具"
                        ),
                    },
                    "timeout": {
                        "type": "number",
                        "description": (
                            f"整体超时秒数 (默认 {DEFAULT_CODE_TIMEOUT_SECONDS:.0f}，"
                            f"上限 {MAX_CODE_TIMEOUT_SECONDS:.0f})"
                        ),
                    },
                },
                "required": ["code"],
            },
        )

    @staticmethod
    def _clamp_timeout(timeout: Any) -> float:
        try:
            t = float(timeout)
        except (TypeError, ValueError):
            return DEFAULT_CODE_TIMEOUT_SECONDS
        return max(1.0, min(t, MAX_CODE_TIMEOUT_SECONDS))

    def execute(self, code: str = "", timeout: Any = DEFAULT_CODE_TIMEOUT_SECONDS, **kwargs: object) -> ToolResult:
        """执行代码 + RPC 桥接（同步；agent 循环已在 executor 线程）"""
        if kwargs:
            return ToolResult(success=False, error="未知参数（合法: code, timeout）")
        if not isinstance(code, str) or not code.strip():
            return ToolResult(success=False, error="code 不能为空")
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            return ToolResult(success=False, error=f"code 超过 {MAX_CODE_BYTES // 1024} KiB 上限")
        effective_timeout = self._clamp_timeout(timeout)

        registry = self._get_registry()
        script = self._write_script(code)
        try:
            return self._run(script, registry, effective_timeout)
        finally:
            import contextlib
            import os

            with contextlib.suppress(OSError):
                os.unlink(script)

    def _write_script(self, user_code: str) -> str:
        """引导 + 用户代码（经 _runner_script 包裹出 done 行）写入临时脚本"""
        import os
        import tempfile

        fd, path = tempfile.mkstemp(prefix="sage-exec-", suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_bootstrap_script())
            fh.write(_runner_script(user_code))
        return path

    def _run(self, script_path: str, registry: Any, timeout: float) -> ToolResult:
        """spawn 子进程 + RPC 桥 + deadline 管理"""
        started = time.monotonic()
        process = subprocess.Popen(  # noqa: S603 — 受控脚本路径
            [sys.executable, "-I", script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        lines: Dict[str, List[str]] = {"out": [], "err": []}
        done_event = threading.Event()
        rpc_queue: List[Dict[str, Any]] = []
        rpc_lock = threading.Lock()

        def _reader(name: str, stream: Any) -> None:
            try:
                for line in iter(stream.readline, ""):
                    with rpc_lock:
                        lines[name].append(line)
                    if name == "out" and line.startswith(RPC_PREFIX):
                        try:
                            payload = json.loads(line[len(RPC_PREFIX) :])
                        except json.JSONDecodeError:
                            continue
                        with rpc_lock:
                            rpc_queue.append(payload)
                        if payload.get("type") == "done":
                            done_event.set()
                if name == "out":
                    done_event.set()
            except Exception:  # noqa: BLE001 — 流关闭
                if name == "out":
                    done_event.set()

        out_thread = threading.Thread(target=_reader, args=("out", process.stdout), daemon=True)
        err_thread = threading.Thread(target=_reader, args=("err", process.stderr), daemon=True)
        out_thread.start()
        err_thread.start()

        deadline = started + timeout
        rpc_served = 0
        final: Optional[Dict[str, Any]] = None
        try:
            while True:
                if done_event.wait(timeout=0.05):
                    # done 后排空可能残留的行
                    with rpc_lock:
                        pending = [p for p in rpc_queue if p.get("type") == "call"]
                        rpc_queue.clear()
                    for payload in pending:
                        self._serve_rpc(registry, process, payload)
                    break
                if time.monotonic() > deadline:
                    process.kill()
                    process.wait(timeout=10)
                    return ToolResult(
                        success=False,
                        error=f"execute_code 超时（{timeout:.0f}s），已终止子进程",
                    )
                with rpc_lock:
                    calls = [p for p in rpc_queue if p.get("type") == "call"]
                    rpc_queue.clear()
                for payload in calls:
                    self._serve_rpc(registry, process, payload)
                    rpc_served += 1
                if process.poll() is not None and done_event.is_set():
                    break
        finally:
            if process.poll() is None:
                process.kill()
                with contextlib.suppress(Exception):
                    process.wait(timeout=5)
            err_thread.join(timeout=2)
            out_thread.join(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                with contextlib.suppress(Exception):
                    stream.close()

        with rpc_lock:
            err_text = "".join(lines["err"])[- _MAX_OUTPUT_CHARS :]
        exit_code = process.returncode

        if final is None and done_event.is_set():
            with rpc_lock:
                for p in lines["out"]:
                    if p.startswith(RPC_PREFIX):
                        try:
                            payload = json.loads(p[len(RPC_PREFIX) :])
                        except json.JSONDecodeError:
                            continue
                        if payload.get("type") == "done":
                            final = payload
        if final is None:
            return ToolResult(
                success=False,
                error={
                    "error": "子进程异常退出",
                    "exit_code": exit_code,
                    "stderr": err_text[-2000:],
                }
                if isinstance(err_text, str)
                else "子进程异常退出",
            )

        ok = bool(final.get("ok"))
        content: Dict[str, Any] = {
            "stdout": "",
            "stderr": err_text,
            "exit_code": exit_code,
            "rpc_calls": rpc_served,
            "result": final.get("value"),
        }
        if not ok:
            content["error"] = final.get("error")
        return ToolResult(success=ok, content=content, error=None if ok else str(final.get("error")))

    def _serve_rpc(self, registry: Any, process: subprocess.Popen, payload: Dict[str, Any]) -> None:
        """执行子进程请求的工具调用并写回结果行"""
        name = payload.get("name")
        arguments = payload.get("arguments") or {}
        try:
            tool = registry.get(name)
            if tool is None:
                ok, value, error = False, None, f"工具不存在: {name}"
            else:
                result = tool.execute(**arguments)
                if hasattr(result, "success") and hasattr(result, "content"):
                    if result.success:
                        value_out = (
                            result.output
                            if getattr(result, "output", None) is not None
                            else result.content
                        )
                        ok, value, error = True, value_out, None
                    else:
                        ok, value, error = False, None, result.error or "工具执行失败"
                else:
                    ok, value, error = True, result, None
        except Exception as exc:  # noqa: BLE001 — 异常回传脚本内处理
            ok, value, error = False, None, str(exc)
        try:
            process.stdin.write(
                json.dumps(
                    {"id": payload.get("id"), "ok": ok, "value": value, "error": error},
                    ensure_ascii=True,
                    default=str,
                )
                + "\n"
            )
            process.stdin.flush()
        except Exception as exc:  # noqa: BLE001 — 子进程已死
            logger.warning("RPC 响应写入失败: %s", exc)
