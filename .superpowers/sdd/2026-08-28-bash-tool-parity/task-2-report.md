# Task 2 报告：跨平台 shell 探测

## 实现

- 新增 `backend/tools/shell_resolver.py`，提供冻结 `ShellSpec`、`resolve_shell()`、`resolve_shell_uncached()` 和 `SHELL_FALLBACK_NOTE`。
- POSIX 按 `/bin/bash`、`/bin/sh` 顺序探测；Windows 按 PATH、`PROGRAMFILES`、`PROGRAMFILES(X86)` 顺序探测 Git Bash，最后降级 PowerShell。
- Windows 候选路径使用 `ntpath.join`，并使用 `os.path.isfile` 拒绝目录伪装；环境根必须是本地绝对路径，拒绝 UNC/相对路径。
- 测试使用 fake/proxy `os`，避免修改宿主进程 `os.name`；PowerShell fallback、明确 PATH、默认 executable、x86 顺序及 frozen dataclass 均独立覆盖。

## 测试

- 按 TDD 先补测试并确认 RED（`isfile` 尚未实现时两项 Program Files 测试失败），再完成实现。
- 最终完整单测：`9 passed`。
- Ruff：通过。
- `git diff --check`：通过。

## Commit

待提交本 fix round 1 commit。

## Concerns

- 测试仍有既有 Pydantic deprecation warnings，不影响结果。
