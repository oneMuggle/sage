# Task 2 报告：跨平台 shell 探测

## 实现

- 新增 `backend/tools/shell_resolver.py`。
- 新增冻结 `ShellSpec` dataclass，提供 `executable`、`args_prefix`、`kind` 字段及 `is_fallback` 属性。
- POSIX 按 `/bin/bash`、`/bin/sh` 顺序探测；Windows 按 PATH、`PROGRAMFILES`/`PROGRAMFILES(X86)` 下 Git Bash 顺序探测，最后降级到 PowerShell。
- 提供精确的 `SHELL_FALLBACK_NOTE` 文案，以及带 `lru_cache(maxsize=1)` 的 `resolve_shell()` 和无缓存测试入口 `resolve_shell_uncached()`。
- 实现使用 `typing.Optional` / `typing.Tuple`，保持 Python 3.8 运行时兼容。

## 测试

- 先按 TDD 创建测试并运行；实现缺失时收集阶段失败，符合预期 RED。
- 实现后 POSIX 场景测试通过（2 passed）。Windows 场景的 monkeypatch 会把当前 Linux 进程的 `os.name` 改成 `nt`，导致 pytest 自身的 `pathlib.Path` 在 teardown 阶段触发 `NotImplementedError: cannot instantiate 'WindowsPath'`; Windows resolver 测试主体已执行并通过（单独运行显示 `1 passed` 后在 pytest teardown 失败）。这是测试环境/pytest 与 `os.name` monkeypatch 的已知兼容性问题，不是 resolver 逻辑失败。
- Ruff：`All checks passed!`
- `git diff --check`：通过。

## Commit

待提交：`feat(tools): 跨平台 shell 探测（POSIX bash / Git Bash / PowerShell 降级）`

## Concerns

- 全量六测试命令在当前 Linux + pytest 运行时因简报要求的 `os.name == "nt"` monkeypatch 触发 pytest teardown 的 WindowsPath 内部错误，无法以 exit code 0 完成；未修改简报指定测试以规避该环境问题。
