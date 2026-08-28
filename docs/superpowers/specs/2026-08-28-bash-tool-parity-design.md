# Bash 命令行工具对齐设计（2026-08-28）

## 背景与目标

sage 的 shell 执行工具 `TerminalTool`（`backend/tools/terminal.py`，162 行）
与 Claude Code 的 Bash tool 存在三处功能缺口，其中第一处是**阻塞级**的：

1. **shell 操作符被硬拦截**。`_is_dangerous()` 调用
   `has_shell_operators()`，任何含 `| && ; > < $( ` 换行` 的命令一律拒绝。
   这让 `ls | head`、`cd build && make`、`grep x f > out` 这类最常见的
   命令全部无法执行 —— 模型实际可用的 shell 面接近于空。
2. **无后台执行**。长任务（dev server、`npm run watch`、
   `pytest --looponfail`）只能同步跑到超时被杀。
3. **输出无上限**。`subprocess.run(capture_output=True)` 在父进程 PIPE
   里无限缓冲，`find /` 这类命令会直接撑爆后端内存。

附带的次级问题：默认超时仅 30s 且无上限约束；超时只杀直接子进程，
孙进程泄漏；Windows 分支靠 `command.startswith("cmd")` 这种脆弱判断
决定是否走 `shell=True`。

**目标**：把 shell 执行能力对齐 Claude Code 的 Bash tool —— 完整 shell
语法、后台执行 + 输出轮询 + 终止、有界输出、进程组回收、跨平台 shell
探测 —— 同时不削弱既有的分层安全模型。

**非目标**：后台进程表持久化（后端重启后残留进程成为孤儿，本次接受，
见 §5.5）；cwd 跨调用持久化（有意选择无状态，见 §4.4）。

## 1. 现状：安全模型分层

改动前，"危险命令"判定存在**两处独立实现**，语义还不一致：

| 层 | 位置 | 作用 |
|---|---|---|
| A. 工具内硬拦截 | `TerminalTool._is_dangerous` | 含 shell 操作符 → 拒；命中 9 条黑名单子串 → 拒 |
| B. 风险分级 | `backend/tools/bash_validation.py`（305 行） | SAFE / SUSPICIOUS / DESTRUCTIVE 三档，含旗标顺序无关的结构化检测 |
| C. 权限裁决 | `backend/tools/permissions.py` `PermissionEnforcer` | 规则(deny>allow>ask) → DESTRUCTIVE 安全网 → 模式矩阵 |
| D. allowlist 防绕过 | `backend/adapters/out/permission/permission_engine.py:217` | allowlist 自动放行前，含 shell 操作符的命令一律不放行（需审批） |

层 B+C 已经覆盖了层 A 想拦的一切，且更严格：`validate_bash` 的
`_rm_destructive_hits` 覆盖 `-fr` / `-r -f` / `--recursive --force` 全部
旗标变体，`PermissionEnforcer._escalate_destructive` 让 DESTRUCTIVE 命令
即使在 `full_access` 模式、即使有显式 allow 规则也强制走用户审批。

层 A 是历史遗留的粗粒度前置拦截，它的 shell 操作符规则把安全性换成了
"几乎不可用"。**本设计删除层 A，危险判定收敛为 B+C 单一来源。**
层 D 保留不动 —— 它解决的是另一个问题（免审批 allowlist 的前缀匹配
绕过），与工具能否执行复合命令无关。

## 2. 命名与引用面

`terminal` → `bash`，与 Claude Code 一致，消除提示词/文档里的叫法分歧。

**文件与类**：

- `backend/tools/terminal.py` → `backend/tools/bash_tool.py`
- `TerminalTool` → `BashTool`
- `schema.name`: `"terminal"` → `"bash"`

**新增文件**：

| 文件 | 职责 |
|---|---|
| `backend/tools/subprocess_util.py` | 从 `repl_tool.py` 提取的共享子进程原语（见 §4.3） |
| `backend/tools/shell_resolver.py` | 跨平台 shell 探测（纯函数 + 缓存） |
| `backend/tools/bash_session.py` | 后台 shell 注册表 |

**新增工具**：`bash_output`、`kill_shell`（均在 `bash_tool.py` 内定义，
共享 `bash_session` 注册表）。

**引用点同步清单**（已逐个核实）：

| 位置 | 改动 |
|---|---|
| `backend/tools/__init__.py` | import + `register_all_tools` + `__all__` |
| `backend/tools/permissions.py:71` `TOOL_CAPABILITIES` | `terminal`→`bash` (EXECUTE)；新增 `bash_output` (READ)、`kill_shell` (WRITE) |
| `backend/domain/risk.py:48` `SHELL_TOOLS` | `{"terminal"}`→`{"bash"}`；`kill_shell` 加入 `WRITE_TOOLS` |
| `backend/agents/profiles.py:109` coder profile | `"terminal"`→`"bash"` |
| `src/shared/lib/humanize.ts:74` | 新增 `bash`/`bash_output`/`kill_shell` case |
| `backend/orchestration/permission.py:58-63` | 注释中的工具名 |
| `backend/tests/integration/test_hooks_integration.py:69,72` | `registry.get("terminal")` |
| `backend/tests/unit/test_risk.py` | 内置工具风险验收表 |
| `backend/tests/unit/test_permission.py:135-139` | 删除 `TerminalTool.SHELL_OPERATORS` 防漂移测试（该类属性不再存在） |

**有意不改的位置**：

- `src/shared/lib/humanize.ts` 的 `case 'terminal'` **保留**。历史会话
  记录里存的工具名是 `terminal`，删掉会让旧对话的工具调用渲染成
  fallback。这是旧数据兼容，不是工具别名。
- `backend/application/services/context_compactor.py:70-78`
  `_ERROR_AWARE_TOOLS` 与 `backend/application/services/export_assets/template.js:287`
  `BASH_NAMES` 本来就同时含 `bash` 和 `terminal`，无需改。
- `backend/domain/shell.py` 不动 —— `PermissionEngine._command_allowed`
  仍需 `has_shell_operators` 做 allowlist 防绕过（层 D）。
- `test_circuit_breaker.py`、`test_permission_routes.py` 里约 130 处
  `"terminal"` 字面量是当"任意工具名"用于测试通用机制的，不动。

**不做 `terminal` 别名**。项目 CLAUDE.md 与全局编码规范均要求避免
向后兼容 shim；重命名一次做干净。

## 3. 工具契约

**`bash(command, cwd=None, timeout=120, run_in_background=False)`**

| 参数 | 类型 | 说明 |
|---|---|---|
| `command` | string，必填 | 完整 shell 命令，允许管道/串联/重定向/命令替换 |
| `cwd` | string，可选 | 工作目录；缺省取 `policy.workspace_root`，未绑定时用进程 cwd |
| `timeout` | number，可选 | 秒；默认 120，夹到 `[1, 600]`；`run_in_background=True` 时忽略 |
| `run_in_background` | bool，可选 | `True` → 立即返回 `shell_id`，不等待 |

**`bash_output(shell_id)`** — 返回增量输出。
**`kill_shell(shell_id)`** — 终止后台 shell 并清理。

## 4. 同步执行语义

### 4.1 shell 选择

`backend/tools/shell_resolver.py` 暴露 `resolve_shell() -> ShellSpec`，
返回 `(executable, args_prefix, kind)`。探测顺序：

- **POSIX**：`/bin/bash` → 不存在退 `/bin/sh`，`args_prefix=["-c"]`
- **Windows**：`shutil.which("bash")` →
  `%PROGRAMFILES%\Git\bin\bash.exe` →
  `%PROGRAMFILES(X86)%\Git\bin\bash.exe`；`args_prefix=["-c"]`
- **Windows 全失败**：退 PowerShell，
  `args_prefix=["-NoProfile", "-Command"]`，`kind="powershell"`

探测结果进程内缓存一次（`functools.lru_cache`），避免每次调用都打文件
系统。实际使用的 shell 写进 `ToolResult.content["shell"]`；PowerShell
降级时额外带 `content["shell_fallback"]` 说明文本，让模型知道 bash
语法（`&&`、`|`、`$()`）可能不适用，而不是对着看不懂的报错反复重试。

Win7 分支（`release/win7`）沿用同一逻辑 —— Win7 上未必装 Git Bash，
PowerShell 降级路径正是为它准备的。

### 4.2 执行方式

统一 `subprocess.Popen([exe, *args_prefix, command], ...)`。

**不用 `shell=True`**：显式 argv 让 shell 只解析一次。`shell=True` 在
POSIX 上等价于再套一层 `/bin/sh -c`，在 Windows 上走 `cmd.exe` 语义，
两边行为分叉且难以推理。删掉旧代码里 `command.startswith("cmd")` 这种
脆弱的平台判断。

### 4.3 输出与进程回收（共享原语）

`repl_tool.py` 已经解决了完全相同的三个问题，且是本仓库验证过的实现。
把三个函数提到 `backend/tools/subprocess_util.py`，`repl_tool` 与
`bash_tool` 共用：

- `make_temp_output_file()` —— 建承接输出的临时文件
- `read_capped_output(path, cap)` —— 只读前 `cap` 字节，返回
  `(text, truncated)`；父进程内存恒定
- `kill_process_tree(process)` —— POSIX `os.killpg` 杀整个进程组
  （连孙进程），Windows 退化 `process.kill()`；随后 `communicate` 回收僵尸

这是消除真实重复，不是投机抽象：两个工具都要跑子进程、都要有界读输出、
都要超时杀进程组。`repl_tool` 的原函数改为从新模块 import，其行为与
现有测试断言不变。

`bash` 的输出上限为各流 30 KiB（stdout / stderr 独立计算）。`repl_tool`
保留自己的 100 KiB 常量 —— 那是它 schema 描述里承诺的值，不改。

### 4.4 超时与 cwd

**超时**：默认 120s，区间 `[1, 600]`，越界夹取（沿用
`repl_tool.clamp_timeout` 的模式）。超时 → 杀进程组 →
`success=False`，错误信息含实际超时值。

**cwd**：无状态。默认取 `policy.workspace_root`，未绑定时用进程 cwd。
每次调用可传 `cwd` 参数覆盖，**不跨调用记忆**。传入的 cwd 走
`BaseTool._enforce_workspace()` 守卫（workspace 外 → 拒绝）。

选择无状态而非 Claude Code 的 "working directory persists" 语义，原因是
sage 的工具实例可能被主 agent 与 `AgentTool` 派生的子代理共享，一方
`cd` 会静默改变另一方的视角，且该状态不出现在任何审批摘要里。既然
shell 操作符已放开，模型想切目录直接写 `cd x && ...` 即可。

### 4.5 成功语义

与 `repl_tool` 一致：

- 命令**非零退出** → `success=True`，`content` 含
  `{exit_code, stdout, stderr, duration_seconds, truncated, shell, cwd}`。
  模型需要看到 stderr 自行纠错，把编译失败当成工具故障会让它无法诊断。
- **超时 / shell 找不到 / Popen 失败** → `success=False` + `error`。

### 4.6 删除的代码

`BashTool` 中不再存在：`_is_dangerous()`、`DANGEROUS_PATTERNS`、
`_has_shell_operators()`、`SHELL_OPERATORS` 类属性、
`command.startswith("cmd")` 分支。

## 5. 后台执行

### 5.1 行为

`bash(run_in_background=True)`：spawn 后立即返回，不等待、不读输出。
`content = {shell_id, command, shell, status: "running", cwd}`。
后台进程**不受 timeout 约束** —— 这正是它存在的理由（dev server、watch）。

`bash_output(shell_id)`：返回自上次读取偏移之后的**增量** stdout/stderr：
`{shell_id, status, stdout, stderr, exit_code, truncated}`。
`status` ∈ `{"running", "exited"}`；`exit_code` 仅在 `exited` 时非 None。
每次调用推进该 session 的读偏移，单次上限 30 KiB/流。

`kill_shell(shell_id)`：杀进程组 → 读走剩余输出 → 删临时文件 →
从注册表移除。`content = {shell_id, killed: true, exit_code, stdout, stderr}`。
已退出的 session 调用它等价于"收尾清理"，不报错。

### 5.2 注册表设计

`backend/tools/bash_session.py`：模块级单例 + `threading.Lock`。工具在
`asyncio.to_thread`（`inproc_adapter`）或 `run_in_executor`
（`legacy/agent.py`）线程里执行，注册表必须线程安全。

```
BashSession:
    shell_id: str          # uuid4().hex
    process: Popen
    command: str
    stdout_path: str       # 内部生成，绝不来自 shell_id
    stderr_path: str
    stdout_offset: int     # 增量读游标
    stderr_offset: int
    started_at: float
```

### 5.3 安全约束

- **shell_id 不参与路径构造**。临时文件路径由
  `tempfile.NamedTemporaryFile` 内部生成并存进 session；`bash_output` /
  `kill_shell` 只用 `shell_id` **查表**取路径。若拼接路径，
  `shell_id="../../etc/passwd"` 就是任意文件读取。未知 shell_id →
  `success=False` + 明确错误，不做任何文件系统操作。
- **容量上限 32**。满时 `bash(run_in_background=True)` 拒绝新建并提示先
  `kill_shell`，防止模型无限起进程耗尽 fd / 内存。
- **审批链不变**。后台 spawn 与同步执行同为 `bash` 工具名，走同一
  `PermissionEnforcer` 裁决；`run_in_background` 只影响执行方式，不构成
  权限旁路。

### 5.4 清理时机

已退出的 session 保留在注册表中，直到显式 `kill_shell` 或容量压力触发
回收 —— 保留是为了让模型在进程退出后仍能读到最后一段输出与 `exit_code`。

### 5.5 已知限制

- **后端重启后后台进程成为孤儿**。注册表是进程内存态，不持久化。这是
  本次有意接受的取舍（持久化需引入 storage 依赖 + 迁移，超出当前需求）。
  会在 `bash_session.py` 模块 docstring 中明确记录。
- **Windows 上杀不到孙进程**。`kill_process_tree` 在 Windows 退化为
  `process.kill()`，与 `repl_tool` 同源限制。

## 6. 权限矩阵映射

| 工具 | `ToolCapability` | `RiskClass` | read_only 下 | workspace_write 下 |
|---|---|---|---|---|
| `bash` | EXECUTE | EXEC | 拒绝 | 逐次审批 |
| `bash_output` | READ | READ | 放行 | 放行 |
| `kill_shell` | WRITE | WRITE_LOCAL | 拒绝 | 放行 |

`bash_output` 归 READ：只读已捕获的输出文件，零副作用。
`kill_shell` 归 WRITE：终止进程是对系统状态的修改，read_only 下应拒。

DESTRUCTIVE 命令安全网（`PermissionEnforcer._escalate_destructive`）
对 `bash` 继续生效 —— `validate_bash` 读 `args["command"]`，参数名不变。

## 7. 实施步骤

- [ ] 步骤 1：提取 `subprocess_util.py`，`repl_tool.py` 改为 import，
      确认 repl 现有测试全绿（纯重构，零行为变化）
- [ ] 步骤 2：`shell_resolver.py` + 单测（POSIX/Windows/降级三路径，
      用 monkeypatch 模拟 `os.name` 与 `shutil.which`）
- [ ] 步骤 3：`bash_session.py` + 单测（注册/查表/增量偏移/容量上限/
      未知 id/路径穿越 id）
- [ ] 步骤 4：`bash_tool.py` 同步执行路径 + 单测（TDD：先写测试）
- [ ] 步骤 5：`bash_tool.py` 后台三工具 + 单测
- [ ] 步骤 6：引用面同步（§2 清单逐项）+ 权限/风险表测试更新
- [ ] 步骤 7：`humanize.ts` 三个新 case + 前端单测
- [ ] 步骤 8：全量 `pytest` + `npm run test` + lint，确认无回归

## 8. 测试计划

**回归（本次核心价值验证）**：`ls | head`、`cd /tmp && pwd`、
`echo a > f && cat f`、`echo $(date)` 在 `workspace_write` + 审批通过后
能真正执行 —— 这些在改动前全部被层 A 拒绝。

**同步执行**：退出码传递；非零退出仍 `success=True` 且 stderr 完整；
超时杀进程组（`sleep 60` + `timeout=1`，断言子进程已死）；
输出超 30 KiB 被截断且 `truncated=True`；cwd 越 workspace 边界被拒；
shell 探测三路径。

**后台**：spawn 返回 `shell_id` 且 `status="running"`；`bash_output`
增量语义（两次读不重复）；进程退出后 `status="exited"` + `exit_code`；
`kill_shell` 真正终止；未知 `shell_id` 报错；`shell_id="../../etc/passwd"`
被拒且不触碰文件系统；容量满时拒绝新建。

**权限**：`bash` 在四种模式下的裁决；`bash_output` 在 read_only 放行；
`kill_shell` 在 read_only 被拒；DESTRUCTIVE 命令在 full_access 仍需审批。

**前端**：`humanize.ts` 对 `bash`/`bash_output`/`kill_shell` 的渲染，
以及 `terminal` 旧值仍正确渲染。

## 9. 风险评估

| 风险 | 缓解 |
|---|---|
| 放开 shell 操作符扩大攻击面 | 层 B+C 覆盖更严（DESTRUCTIVE 强制审批，显式 allow 规则也无法绕过）；层 D allowlist 防绕过保留不动 |
| 重命名遗漏引用点导致工具消失 | §2 清单已逐个 grep 核实；步骤 8 全量测试兜底 |
| `subprocess_util` 提取破坏 repl | 步骤 1 为纯移动，repl 现有测试作为回归门禁 |
| 后台进程泄漏 | 容量上限 32 + `kill_shell` + docstring 明确记录重启孤儿限制 |
| Win7 无 Git Bash | PowerShell 降级路径 + `shell_fallback` 提示 |

## 10. 依赖

无新增第三方依赖。仅用标准库 `subprocess` / `tempfile` / `threading` /
`shutil` / `uuid` / `functools`。Python 3.8 兼容（`start_new_session` 是
3.2+ 关键字参数），`release/win7` 分支可 cherry-pick。
