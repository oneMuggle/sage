# bash 命令行工具

> 对齐 Claude Code Bash tool 的 shell 执行能力。取代原 `terminal` 工具。

## 为什么重写

原 `TerminalTool` 在工具内部做危险命令拦截，规则之一是「含任何 shell
操作符（`| && ; > < $( ` 换行`）即拒绝」。后果是 `ls | head`、
`cd build && make`、`grep x f > out` 这类最常见的命令全部无法执行 ——
模型实际可用的 shell 面接近于空。

危险判定现在只有一处来源：

| 层 | 位置 | 职责 |
|---|---|---|
| 风险分级 | `backend/tools/bash_validation.py` | SAFE / SUSPICIOUS / DESTRUCTIVE 三档 |
| 权限裁决 | `backend/tools/permissions.py` `PermissionEnforcer` | 规则(deny>allow>ask) → DESTRUCTIVE 安全网 → 模式矩阵 |
| allowlist 防绕过 | `backend/adapters/out/permission/permission_engine.py` | 免审批 allowlist 前，含 shell 操作符的命令不自动放行 |

这条链比旧的子串黑名单更严：`validate_bash` 覆盖 `rm -fr` / `rm -r -f` /
`--recursive --force` 全部旗标变体，且 DESTRUCTIVE 命令即使在
`full_access` 模式、即使有显式 allow 规则也强制走用户审批。

## 三个工具

| 工具 | 能力 | 用途 |
|---|---|---|
| `bash` | EXECUTE | 执行命令（同步或后台） |
| `bash_output` | READ | 读后台 shell 的增量输出 |
| `kill_shell` | WRITE_LOCAL | 终止后台 shell 并清理 |

### bash

| 参数 | 默认 | 说明 |
|---|---|---|
| `command` | 必填 | 完整 shell 命令，允许管道/串联/重定向/命令替换 |
| `cwd` | `policy.workspace_root` | 工作目录；**不跨调用保留** |
| `timeout` | 120 秒 | 夹到 `[1, 600]`；后台执行时忽略 |
| `run_in_background` | `false` | `true` 则立即返回 `shell_id` |

同步返回 `{exit_code, stdout, stderr, duration_seconds, truncated, shell, cwd}`。

**命令非零退出仍 `success=True`** —— 模型需要看到 stderr 自行纠错；把编译
失败当成工具故障会让它无法诊断。只有超时、shell 找不到、进程启动失败才
`success=False`。

**cwd 无状态**是有意选择，而非疏漏。工具实例可能被主 agent 与 `AgentTool`
派生的子代理共享，持久化 cwd 会让一方 `cd` 静默改变另一方的视角，且该状态
不出现在任何审批摘要里。既然 shell 操作符已放开，切目录写 `cd x && ...` 即可。

### 后台执行

`bash(run_in_background=true)` 起的进程登记在
`backend/tools/bash_session.py` 的进程级注册表中，**不受 timeout 约束** ——
这正是它存在的理由（开发服务器、watch 模式）。

`bash_output` 每次只返回上次读取之后的**增量**输出（注册表为每个会话维护
stdout/stderr 读游标），并报告 `status`（`running` / `exited`）与
`exit_code`。

`shell_id` 是 `uuid4().hex`，**绝不参与路径构造** —— 临时输出文件路径在注册
时生成并存进会话记录，读取只用 `shell_id` 查表。若拼接路径，
`shell_id="../../etc/passwd"` 就成了任意文件读取。

## 已知限制

- **后端重启后后台进程成为孤儿**。注册表是进程内存态，不持久化。持久化
  需要引入 storage 依赖与表迁移，超出当前需求。容量上限 32
  （`MAX_BACKGROUND_SESSIONS`）限制单次运行期间的泄漏规模。
- **Windows 上杀不到孙进程**。`subprocess_util.kill_process_tree` 在
  Windows 退化为 `process.kill()`，与 `repl` 工具同源限制。

## 跨平台 shell 探测

`backend/tools/shell_resolver.py` 按序探测（结果进程内缓存一次）：

- POSIX：`/bin/bash` → `/bin/sh`
- Windows：PATH 中的 `bash` → `%PROGRAMFILES%\Git\bin\bash.exe` →
  `%PROGRAMFILES(X86)%\Git\bin\bash.exe`
- Windows 全失败：PowerShell（`-NoProfile -Command`），结果中带
  `shell_fallback` 提示，让模型知道 bash 语法可能不适用

`release/win7` 分支尤其依赖 PowerShell 降级路径 —— Win7 机器未必装 Git。

## 输出与进程回收

`backend/tools/subprocess_util.py` 提供 `bash` 与 `repl` 共用的原语：

- 子进程 stdout/stderr 重定向到**临时文件**而非父进程 PIPE。PIPE 会无限
  缓冲，命令打印几个 GB 就撑爆后端内存。
- 只读前 30 KiB（`bash`）/ 100 KiB（`repl`），超出加截断标记。
- `start_new_session=True` + 超时 `os.killpg` 杀整个进程组（连孙进程）。