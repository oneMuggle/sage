# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Windows 工具链环境快照（PR1：环境事实前置可见）。

背景：win7 机器上 PowerShell 常为 2.0（不支持 PS 5.0+ 参数），系统
python/node 路径参差。此前这些事实只在 bash 工具 fallback 时才出现在
*单次 tool result* 里（bash_tool._decorate → build_shell_fallback_note），
agent 不调用 bash 就完全无感知，同一环境坑反复试错（Win7 用户反馈）。

本模块把 shell/版本/解释器路径汇总成一份稳定文本，经
profiles.build_system_base() 注入所有链路（legacy/hex/子代理）的
system prompt 头部。全部 fail-safe：单项探测失败省略该行，整体失败返回
空串，绝不阻断聊天。

TTL 缓存（默认 10 分钟）：装 Git for Windows / 升级 WMF 后无需重启后端
即可在下一份快照生效；快照字符串极少变化，不影响 prefix cache。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

#: 快照缓存有效期（秒）。期间重复调用零探测开销。
SNAPSHOT_TTL_SECONDS = 600.0

#: 单个 `--version` 探测的子进程超时（秒）。
_PROBE_TIMEOUT_SECONDS = 5.0

_cache = {"text": None, "expires_at": 0.0}

#: per-session 工具观察缓冲（bash fallback 等环境 note → 轮末进记忆蒸馏）。
#: 有界：每 session 最多 _OBS_MAX_PER_SESSION 条、单条截 _OBS_MAX_CHARS。
_obs_lock = threading.Lock()
_observations: dict = {}
_OBS_MAX_PER_SESSION = 3
_OBS_MAX_CHARS = 200


def record_observation(session_id: Optional[str], text: str) -> None:
    """记录一条本轮工具执行观察到的环境事实（best-effort，绝不抛错）。"""
    if not session_id or not text:
        return
    text = text.strip()[:_OBS_MAX_CHARS]
    if not text:
        return
    with _obs_lock:
        bucket = _observations.setdefault(session_id, [])
        if text not in bucket:
            bucket.append(text)
            del bucket[:-_OBS_MAX_PER_SESSION]


def pop_observations(session_id: Optional[str]) -> str:
    """取出并清空该 session 的观察记录（拼为多行文本；无记录返回空串）。"""
    if not session_id:
        return ""
    with _obs_lock:
        bucket = _observations.pop(session_id, None)
    return "\n".join(bucket) if bucket else ""


def _command_version(exe: str) -> str:
    """执行 ``exe --version``，取第一行输出；失败返回空串。"""
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
        out = (result.stdout or result.stderr or "").strip()
        return out.splitlines()[0].strip() if out else ""
    except Exception as exc:  # noqa: BLE001 — 探测失败只省略该行
        logger.debug("探测 %s --version 失败: %s", exe, exc)
        return ""


def probe_python() -> str:
    """系统 Python 事实：``版本 (路径)``，找不到返回 ``未检测到``。"""
    for name in ("python", "python3", "py"):
        exe = shutil.which(name)
        if not exe:
            continue
        version = _command_version(exe)
        if version:
            return f"{version} ({exe})"
    return "未检测到"


def probe_node() -> str:
    """Node.js 事实：``版本 (路径)``；有路径但版本失败时只给路径。"""
    exe = shutil.which("node")
    if not exe:
        return "未检测到"
    version = _command_version(exe)
    return f"{version} ({exe})" if version else exe


def build_snapshot(force_refresh: bool = False) -> str:
    """构建（或取缓存的）Windows 工具链快照；非 Windows 恒返回空串。

    Args:
        force_refresh: 忽略 TTL 缓存立即重探（测试/排障用）。
    """
    if os.name != "nt":
        return ""
    now = time.time()
    if not force_refresh and _cache["text"] is not None and now < _cache["expires_at"]:
        return _cache["text"]
    try:
        text = _build_snapshot_uncached()
    except Exception as exc:  # noqa: BLE001 — 快照失败不影响对话
        logger.warning("构建 Windows 环境快照失败: %s", exc)
        return ""
    _cache["text"] = text
    _cache["expires_at"] = now + SNAPSHOT_TTL_SECONDS
    return text


def reset_cache() -> None:
    """清空快照缓存（测试用）。"""
    _cache["text"] = None
    _cache["expires_at"] = 0.0


def _build_snapshot_uncached() -> str:
    from backend.tools.shell_resolver import (
        detect_powershell_version,
        get_bundled_python_path,
        resolve_shell,
    )

    lines = []

    ps_version = None
    try:
        shell = resolve_shell()
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_shell 失败: %s", exc)
        lines.append("- bash/repl 执行 shell: 探测失败，请按 PowerShell 语法书写命令")
    else:
        if shell.kind == "powershell":
            ps_version = detect_powershell_version() or "未知"
            lines.append(
                f"- bash/repl 执行 shell: Windows PowerShell {ps_version} ({shell.executable})；"
                "未找到可用的 bash"
            )
        else:
            lines.append(
                f"- bash/repl 执行 shell: {shell.kind} ({shell.executable})"
            )

    if ps_version is not None and (ps_version.startswith("2.") or ps_version == "未知"):
        lines.append(
            "- PowerShell 2.0 不支持 -Directory/-File/-LiteralPath 等 PS 5.0+ 参数；"
            "用 `Get-ChildItem | Where-Object { $_.PSIsContainer }` 替代 `-Directory`，"
            "用 `Test-Path -PathType Container` 判断目录。"
        )

    bundled_python = get_bundled_python_path()
    if bundled_python:
        lines.append(
            f"- Sage 自带 Python: {bundled_python}（系统 python 缺失/版本不符时直接使用，"
            "不要扫描系统盘）。"
        )
    lines.append(f"- 系统 Python: {probe_python()}")
    lines.append(f"- Node.js: {probe_node()}")
    lines.append(
        "- 书写 shell/REPL 命令前先核对本快照；因版本/路径问题试错出可用写法后，"
        "用 memory_save 固化该事实（memory_type='semantic', importance=8, "
        "tags=['environment']），避免下次重复踩坑。"
    )

    return "<windows-environment>\n{}\n</windows-environment>".format("\n".join(lines))


__all__ = [
    "SNAPSHOT_TTL_SECONDS",
    "build_snapshot",
    "pop_observations",
    "probe_node",
    "probe_python",
    "record_observation",
    "reset_cache",
]
