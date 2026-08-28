# Task 2 报告：跨平台 shell 探测

## Fix round 3 实现

- POSIX `/bin/bash`、`/bin/sh` 继续按顺序使用 `os.path.isfile`，两者均不可用时显式抛出 `RuntimeError`，不再无条件返回 `/bin/sh`。
- Windows 最终 executable 验证增加 `_verify_windows_file_identity`：使用 `GetFileAttributesW` 拒绝 reparse point，并通过 `CreateFileW` + `GetFinalPathNameByHandleW` 比较最终解析路径；句柄、API、返回长度或属性验证失败均 fail closed。Git Bash 与 PowerShell 均经过该验证。
- Win32 known-folder/system-directory helper 继续惰性调用，不读取可控环境变量；`GetWindowsDirectoryW` 严格拒绝负值、零值及大于等于 buffer size，`SHGetFolderPathW` 仅接受零 HRESULT 与非空本地绝对路径。

## 测试

- TDD RED：先新增 POSIX 无 shell、reparse 最终路径外逸及 API 验证契约测试，旧实现失败。
- 目标单测：`25 passed`。
- Ruff：通过。
- `git diff --check`：通过。

## Commit

待提交本 fix round 3 commit。

## Concerns

- 测试使用 fake/proxy `os` 和独立 helper monkeypatch，未污染宿主 `os.name`。
- Linux 无法真实验证 Windows symlink/junction/reparse 与 Win32 handle 行为；代码对 API 缺失、异常、invalid handle 和非法长度均 fail closed，限制已由测试中的最终路径拒绝用例覆盖。
- 无新增依赖，代码保持 Python 3.8 兼容。
