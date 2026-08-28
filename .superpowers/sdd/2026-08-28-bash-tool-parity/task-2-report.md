# Task 2 报告：跨平台 shell 探测

## Fix round 5 实现

- 修正 `_canonical_windows_path` 对真实 `\\?\\` Win32 扩展前缀的识别；扩展 DOS 路径现在可与对应普通 DOS 路径精确匹配，UNC、device 和非本地路径仍不进入信任边界。
- `_verify_windows_file_identity` 继续使用显式 `ctypes.wintypes` ABI、目标及父目录 reparse 检查、`FILE_FLAG_OPEN_REPARSE_POINT` 和最终路径精确比较；最终路径返回值异常/越界、Win32 API 异常、无效句柄均 fail closed。`CloseHandle` 返回 False 或抛异常时也 fail closed，且不会覆盖已完成的验证结果。
- POSIX 继续要求 regular file 与 `os.access(..., os.X_OK)`；未找到合格 shell 时显式失败。未修改 `ShellSpec` 公共字段。

## 测试

- TDD RED/GREEN：新增扩展前缀回归、独立 helper 覆盖、父目录/目标 reparse、属性/创建 API 异常、invalid handle、最终路径 0/等于或超过 buffer 长度/异常、CloseHandle 成功/失败/异常，以及 ABI 属性断言。
- `backend/tests/unit/test_shell_resolver.py`：`38 passed`。
- 相关测试（shell resolver、subprocess util、repl tool）：`78 passed`。
- Ruff：`All checks passed`。
- `git diff --check`：通过。

## Commit

`a50544b93f5d79eebf4ae7597536aa4c96eb2e60`（fix(tools): validate Windows shell final paths）

## Concerns

- 测试在 Linux 上使用 fake kernel32，无法真实执行 Windows symlink/junction/reparse 集成语义。
- resolver 字符串接口导致验证完成到后续 `Popen` 调用之间仍存在 TOCTOU 残余；本 Task 未改变 `ShellSpec` schema。
- 无新增依赖，代码保持 Python 3.8 兼容；测试仍有既有 Pydantic deprecation warnings。
