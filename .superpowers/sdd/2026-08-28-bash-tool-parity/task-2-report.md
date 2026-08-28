# Task 2 报告：跨平台 shell 探测

## 实现

- 保留 `ShellSpec`、`resolve_shell()`、`resolve_shell_uncached()` 与 `SHELL_FALLBACK_NOTE` 接口，以及 POSIX `/bin/bash`、`/bin/sh` 和 Windows PATH → `PROGRAMFILES` → `PROGRAMFILES(X86)` → PowerShell 探测顺序。
- 增加本地 Windows 绝对路径校验：要求非空盘符、盘符后以 `\\` 或 `/` 开头，拒绝 rooted、drive-relative、UNC、device 与相对路径。
- Git Bash 与 PowerShell 候选均要求 regular file；PATH bash 仅接受可信的 `Git\\bin\\bash.exe` 形态，PowerShell 仅接受可信 PATH 文件或 `SystemRoot`/`WINDIR` 系统路径，彻底移除裸 `powershell.exe` fallback。
- 测试通过 fake/proxy `os` 隔离，未 monkeypatch 宿主 `os.name`；保留原有行为并补充不可信路径、目录、环境根、可信系统 fallback 与显式失败覆盖。

## 测试

- TDD RED：先新增安全契约测试，旧实现对不可信 PATH、裸 PowerShell 和系统 fallback 测试失败。
- 目标单测：`23 passed`。
- Ruff：`All checks passed`。
- `git diff --check`：通过。

## Commit

`fix(tools): validate trusted Windows shell executables`（见下方 commit hash）。

## Concerns

- 测试环境使用 Python 3.10 的 `sage-backend` 环境；实现仅使用 Python 3.8 兼容语法。
- 测试仍有既有 Pydantic deprecation warnings，不影响结果。
- 相较旧 brief 中“任意 PATH bash”断言，本 fix round 按安全审查要求收紧为仅可信 Git `Git\\bin\\bash.exe`，并拒绝可能被 PATH 劫持的裸 PowerShell 文件名。
