# 2026-09-18 bash/repl 工具：中文编码 + repl 资源清理修复

## 背景与目标

bash 工具和 repl 工具存在两个缺陷：

1. **中文路径编码问题**：子进程输出编码（Windows 中文系统默认 GBK/CP936）与读取端硬编码 UTF-8 不匹配，导致含中文路径/文件名/内容的输出出现乱码或 `` 替换字符
2. **repl 资源清理失效**：`_run_subprocess()` finally 块在临时文件清理失败时 `raise` 异常，覆盖了已成功执行的 REPL 结果，导致实际 stdout/stderr 丢失；另外 pending 清理无定时器，仅在下次 REPL 调用或后端关闭时重试

## 涉及的文件与模块

| 文件 | 修改内容 |
|------|----------|
| `backend/tools/subprocess_util.py` | `read_capped_output()` 增加 fallback 解码；`spawn_verified()` 支持 `extra_env` 参数 |
| `backend/tools/bash_tool.py` | `_spawn()` 注入编码环境变量到子进程 |
| `backend/tools/repl_tool.py` | finally 块不再 raise；增加后台定时清理线程 |
| `backend/tools/shell_resolver.py` | PowerShell 实际执行命令时注入 UTF-8 编码前缀 |

## 技术方案

### 修复 1：中文编码问题

**核心思路**：让子进程输出 UTF-8，而不是在读取端猜测编码。

1. `spawn_verified()` 新增 `extra_env: Optional[Dict[str, str]] = None` 参数，Popen 时合并到 `env`（继承父进程 env + 覆盖指定项）。向后兼容。

2. `read_capped_output()` 增加 fallback：先 UTF-8 解码，若结果含 `` 替换字符，则用 `locale.getpreferredencoding()` fallback 重试。兼容不遵守环境变量的 Windows 原生程序。

3. bash 工具 `_spawn()`：注入 `LANG=C.UTF-8`、`LC_ALL=C.UTF-8`、`PYTHONUTF8=1`。Windows PowerShell 路径：在命令前加 UTF-8 编码前缀（扩展 `shell_resolver.py` 已有的模式）。

4. repl 工具 `_run_subprocess()`：注入 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`。

### 修复 2：repl 资源清理失效

1. `finally` 块中 `raise final_cleanup_error`（`repl_tool.py:534`）改为 `logger.error()` 不 raise。文件清理是 best-effort，不应覆盖已成功的执行结果。

2. 新增 `_start_periodic_cleanup_timer()`：首次 `_retain_pending_cleanup()` 时启动 daemon 线程，每 60 秒调用 `_retry_pending_cleanups()`，队列空时自动停止。

## 实施步骤

- [x] 步骤 1：`subprocess_util.py` — `spawn_verified()` 增加 `extra_env`；`read_capped_output()` fallback 解码
- [x] 步骤 2：`bash_tool.py` — `_spawn()` 注入编码环境变量
- [x] 步骤 3：`repl_tool.py` — finally 不 raise + 定时清理线程
- [x] 步骤 4：PowerShell 路径在 `bash_tool._spawn()` 注入 UTF-8 前缀（而非 resolver）
- [x] 步骤 5：补充单元测试（共新增 7 个测试类/函数，172 个测试全绿）
- [x] 步骤 6：cherry-pick 到 release/win7 分支对齐（PR #1119 已开，py38 测试 253 个全绿）

## 风险评估

- `spawn_verified()` 新增 optional 参数，所有现有调用方不受影响
- PowerShell UTF-8 前缀放在命令最前面，后续命令可覆盖
- 定时清理线程使用已有 `_PENDING_CLEANUPS_LOCK`，线程安全
- fallback 解码仅在检测到 `` 时触发，性能影响可忽略

## 依赖

- 无外部依赖变更
- stdlib: `ctypes`（Windows GetACP）、`locale`（POSIX 编码探测）
