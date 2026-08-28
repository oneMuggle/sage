# Task 2 报告：跨平台 shell 探测

## 实现

- 保留 `ShellSpec`、`resolve_shell()`、`resolve_shell_uncached()` 与 `SHELL_FALLBACK_NOTE` 接口及既定探测顺序。
- POSIX `/bin/bash`、`/bin/sh` 均改用 `os.path.isfile`，不接受目录。
- Windows 不读取 `PROGRAMFILES`、`PROGRAMFILES(X86)`、`SystemRoot` 或 `WINDIR`；通过惰性 Win32 API helper 获取 known Program Files roots（`SHGetFolderPathW`）和系统目录（`GetWindowsDirectoryW`）。API 不可用时安全返回空结果。
- PATH bash 仅当 regular file 且规范路径严格等于 known Program Files root + `Git\\bin\\bash.exe` 时接受；安装目录按 API 返回顺序探测。PowerShell 完全不信任 PATH，仅从 API 系统目录构造标准路径并要求 regular file。
- 继续拒绝 rooted、drive-relative、UNC、device、相对路径；测试通过 fake/proxy `os` 与 monkeypatch helper 隔离，未修改宿主 `os.name`。

## 测试

- TDD RED：先调整测试验证旧的后缀信任、环境变量信任、PATH PowerShell 和 `exists` 行为失败。
- 目标单测：`24 passed`。
- Ruff：`All checks passed`。
- `git diff --check`：通过。

## Commit

待提交本 fix round 2 commit。

## Concerns

- 测试环境使用 Python 3.10 的 `sage-backend`；实现保持 Python 3.8 兼容且无新增依赖。
- 测试运行仍有既有 Pydantic deprecation warnings。
- Linux fake 测试无法验证真实 Windows symlink/reparse-point 语义；实现至少使用 Win32 API 信任根、严格路径比较和 regular-file 校验，不扩大候选范围。
- 相较旧 brief 中“任意 PATH bash”与环境变量构造路径，本轮按安全审查要求改为 only Win32 known-folder/system-directory API 来源。
