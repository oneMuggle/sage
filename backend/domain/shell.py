"""Shell 命令安全共享定义（A7/A1）。

Shell 操作符的单一来源，由 ``TerminalTool``（A7 危险命令检查）与
``PermissionEngine``（A1 命令 allowlist 防绕过）共同 import，从结构
上消除两处手工同步的漂移风险（一侧新增操作符另一侧遗漏会产生
allowlist 绕过面）。

**领域纯净性**：本模块仅依赖标准库。
"""

from __future__ import annotations

# Shell 操作符：任一出现即把"一条白名单命令"变成多条。携带这些字符
# 的命令不得走 allowlist 自动放行 — 必须显式审批。覆盖串联（`;` `&`
# `&&` `||`）、管道（`|`）、重定向（`>` `<`）、命令替换（`` ` `` `$(`）、
# 进程替换/分组（`(`）与换行。
SHELL_OPERATORS = (";", "&", "|", ">", "<", "`", "$(", "(", "\n", "\r")


def has_shell_operators(command: str) -> bool:
    """命令是否携带 shell 操作符（串联/管道/重定向/替换/分组）。"""
    return any(op in command for op in SHELL_OPERATORS)
