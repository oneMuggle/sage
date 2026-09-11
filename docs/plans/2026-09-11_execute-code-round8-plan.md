# ExecuteCode 零上下文工具调用 Round 8 实施计划（对标 hermes execute_code）

> 日期: 2026-09-11 · 分支: `feat/execute-code-rpc` · 基于 main @ 597e89e3
> 来源: hermes-agent 对标分析（code execution / RPC tool calling）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。
> 冲突规避: 避开 p11-embedding / parity-r9 / word-format-spec 在飞区域。

## 背景

Agent 逐次调用工具时，每次调用都消耗一次完整 LLM 往返（请求 + 工具结果
注入 + 下一次请求）。hermes 的 `execute_code` 让 agent 写一段 Python、
脚本内经 RPC 直接调用工具 —— **N 次工具调用只占一次往返**，批量文件
处理/数据分析/多步机械操作的场景下上下文效率数量级提升。

## 方案

### A. `backend/tools/execute_code_tool.py`（新）

- `ExecuteCodeTool(registry, policy)`，`risk = EXEC`（子进程可执行任意
  代码，权限面与 bash 等同，走 M1 权限执行器审批）
- 子进程 `python -I` 隔离 import/环境（与 repl 同级，非 OS 沙箱）
- **RPC 协议**：JSON 行、`##RPC##` 前缀行走真实 stdout；用户 print
  重定向 stderr；父进程 reader 线程 + 主循环 serve；`sage.call(name,
  **args)` 阻塞等响应，失败抛 RuntimeError 由脚本内处理
- 编码健壮性：子进程 stdout/stdin/stderr 显式 `reconfigure(utf-8)`
  （Windows 管道默认 GBK；`-I` 忽略 PYTHONIOENCODING）+ 父进程响应
  `ensure_ascii=True`（纯 ASCII 对任何子进程编码都安全）
- done 行（成功/异常都回传，含 traceback）+ 整体 deadline kill +
  单条 update 失败不中断 + 输出上限截断

### B. 注册

- `tools/__init__.py`: import + register（registry 注入）
- `domain/tool_names.py`: `SANDBOX_TOOLS += execute_code`
- `test_risk.py` 验收表: `execute_code → EXEC`

### C. 测试

- `backend/tests/unit/test_execute_code.py`：纯代码执行/RPC 单调用/
  循环 N 次 RPC（核心收益断言）/RPC 异常脚本内捕获/未知工具/空 code/
  未知参数/超时杀进程/语法错误

## 验收

- [ ] 新测试全绿 + 存量 risk/registry 测试不回归
- [ ] ruff 干净；CI 覆盖率 ≥80% 绿
- [ ] PR 注明「新功能，不 cherry-pick 到 release/win7」
