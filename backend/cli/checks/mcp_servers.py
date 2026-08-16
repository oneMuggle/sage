"""检查 $SAGE_USER_DATA_DIR/mcp_servers.json 中每个 server 的 command 可解析。

诊断:MCP server 配置错误(命令路径写错、可执行文件不存在)会在用户首次
调用 MCP 工具时才暴露,排查链长。本 check 启动期提前发现"command 找不到"。

兼容 backend/mcp/config.py 的查找策略(env 优先,fallback 到 <project>/backend/data/mcp_servers.json)。
本 check 不引入 backend.mcp 依赖(避免冷启动对 mcp 包的强依赖,doctor 须 stdlib-only)。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register


def _resolve_mcp_config_path() -> Path:
    """复刻 backend/mcp/config.py 的查找顺序,避免 import 整个 mcp 包。

    1. $SAGE_USER_DATA_DIR/mcp_servers.json
    2. <project_root>/backend/data/mcp_servers.json  (从 doctor.py 所在目录上溯)
    """
    env = os.environ.get("SAGE_USER_DATA_DIR")
    if env:
        return Path(env) / "mcp_servers.json"
    # 找 backend/data/mcp_servers.json (doctor 包布局: backend/cli/checks/<this>.py)
    return Path(__file__).resolve().parents[2] / "data" / "mcp_servers.json"


def _command_resolvable(command: str) -> tuple:
    """检查 command 是否可解析为可执行文件。

    Returns (ok, reason)。reason 仅为日志/提示用。
    """
    if not command or not command.strip():
        return False, "command 为空"
    # 1. 绝对路径 / 含路径分隔符 → 直接检查文件存在 + 可执行
    if os.sep in command or (os.altsep and os.altsep in command):
        p = Path(command)
        if not p.exists():
            return False, f"文件不存在: {command}"
        if not os.access(str(p), os.X_OK):
            return False, f"文件不可执行: {command}"
        return True, "OK"
    # 2. 纯命令名 → 走 PATH 查找
    resolved = shutil.which(command)
    if resolved is None:
        return False, f"PATH 中找不到: {command}"
    return True, "OK"


@register
class McpServersCheck:
    name = "mcp_servers"
    description = "MCP server 配置(command 可解析性)"

    def run(self) -> CheckResult:
        path = _resolve_mcp_config_path()
        if not path.exists():
            return CheckResult(
                self.name,
                Severity.INFO,
                f"未配置 MCP server({path.name} 不存在)",
            )

        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"{path.name} 解析失败: {exc.__class__.__name__}: {exc}",
                f"检查 {path} 的 JSON 合法性,或删除该文件让系统重建",
            )

        servers = data.get("servers") if isinstance(data, dict) else None
        if not isinstance(servers, list) or not servers:
            return CheckResult(
                self.name,
                Severity.INFO,
                "MCP server 列表为空",
            )

        invalid: list = []
        for srv in servers:
            if not isinstance(srv, dict):
                invalid.append("(非 dict 元素)")
                continue
            name = srv.get("name") or "<unnamed>"
            command = srv.get("command") or ""
            enabled = srv.get("enabled", True)
            if not enabled:
                continue
            ok, reason = _command_resolvable(command)
            if not ok:
                invalid.append(f"{name}: {reason}")

        if invalid:
            joined = "; ".join(invalid)
            return CheckResult(
                self.name,
                Severity.WARN,
                f"{len(invalid)}/{len(servers)} MCP server 不可解析: {joined}",
                "在 MCP 设置页修正 command 路径,或禁用已迁移的 server",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            f"{len(servers)} 个 MCP server 全部可解析",
        )
