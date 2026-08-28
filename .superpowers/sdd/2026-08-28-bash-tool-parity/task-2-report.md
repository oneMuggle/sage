# Task 2 报告：跨平台 shell 探测

## Fix round 4 实现

- 为 Win32 API 引入 `ctypes.wintypes` ABI 声明，配置 known-folder、system-directory、文件属性、句柄打开、最终路径和关闭句柄的 `argtypes/restype`，并使用可靠的 invalid handle 检查。
- `_verify_windows_file_identity` 使用 `FILE_FLAG_OPEN_REPARSE_POINT`，检查目标及父目录链的 `FILE_ATTRIBUTE_REPARSE_POINT`，读取最终句柄路径并与 expected 精确规范化比较；异常、API 缺失、无效句柄、非法长度全部 fail closed。Git Bash 与 PowerShell 共用。
- POSIX 现在要求 `isfile` 且 `os.access(..., os.X_OK)`，无合格 shell 时显式抛错。

## 测试

- TDD RED：先补 ABI/reparse、父链/最终路径、invalid handle、API 异常、长度越界、CloseHandle 和 POSIX 执行权限测试，旧实现失败。
- 目标单测：`25 passed`。
- Ruff：通过。
- `git diff --check`：通过。

## Commit

待提交本 fix round 4 commit。

## Concerns

- Linux fake 测试直接覆盖 kernel32 fake 的有效 handle、最终路径、reparse、invalid handle 和关闭句柄行为，但无法真实执行 Windows symlink/junction/reparse 语义。
- resolver 公共接口只能返回字符串；验证完成到调用方后续 `Popen` 之间仍存在 TOCTOU 路径替换窗口，需由调用方缩短间隔或使用受保护安装目录/launch-time revalidation 进一步防护，本 Task 未改变 `ShellSpec` schema。
- 无新增依赖，代码保持 Python 3.8 兼容；测试仍有既有 Pydantic deprecation warnings。
