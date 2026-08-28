# Task 2 报告：跨平台 shell 探测

## 实现

- 新增 `backend/tools/shell_resolver.py`。
- 新增冻结 `ShellSpec` dataclass，提供 `executable`、`args_prefix`、`kind` 字段及 `is_fallback` 属性。
- POSIX 按 `/bin/bash`、`/bin/sh` 顺序探测；Windows 按 PATH、`PROGRAMFILES`/`PROGRAMFILES(X86)` 下 Git Bash 顺序探测，最后降级到 PowerShell。
- 提供精确的 `SHELL_FALLBACK_NOTE` 文案，以及带 `lru_cache(maxsize=1)` 的 `resolve_shell()` 和无缓存测试入口 `resolve_shell_uncached()`。
- Windows Git Bash 路径使用 `ntpath.join`，确保在任意测试宿主上生成反斜杠路径。
- 实现使用 `typing.Optional` / `typing.Tuple`，保持 Python 3.8 运行时兼容。

## 测试

- 修复前先更新测试并运行 RED：Program Files 场景因原实现使用被 fake 的 `os.path` 而失败。
- 测试改用 fake/proxy `os` 对象，不再修改全局 `os.name`，并新增 `PROGRAMFILES(X86)` 顺序与路径断言。
- 修复后完整测试：`6 passed`。
- Ruff：`All checks passed!`
- `git diff --check`：通过。

## Commit

`e0062ea9`（Task 2 初始实现）；本轮修复待提交。

## Concerns

- 测试输出包含既有 Pydantic deprecation warnings，不影响结果。
