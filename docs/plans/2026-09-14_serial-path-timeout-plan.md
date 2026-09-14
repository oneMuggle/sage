# R32 批次 H —— legacy 串行主路径接入中心超时（切片 A 延伸）

> 背景：#705 给并行只读批次接入了中心超时；串行主路径（生产分发点，
> `_await_tool_execution`）此前无超时保护——挂死的工具会让整轮停滞。

## 范围（关键边界）
- **覆盖**：非 agent、非 dispatch_subagents、非阻塞型（is_blocking=False）
  的普通工具执行（inline 同步与 executor 分支）。
- **排除**（保持既有语义）：
  - `agent` / `dispatch_subagents`：子代理合法长跑（分钟级），
    中心超时会打断正常任务；
  - `is_blocking=True`（如 bash 会话）：工具内部自带会话级超时管理；
- 超时值：`tool_policy.timeout_seconds`；None/0 = 关闭（旧行为）。
- 超时后：执行任务被取消（executor 线程尽力等自然超时，事件循环立即
  恢复），返回 success=False 的错误结果（文案与并行批次/hex 统一）。

## 改动
- `_await_tool_execution`：对覆盖范围内的执行协程加
  `asyncio.wait_for`；超时返回
  `SimpleNamespace(success=False, content=None, error=tool_timeout_message)`。
- 消费方既有 result-attr 分支自然处理（is_error=True + 文案落观察结果）。

## 测试
- 挂死 inline 工具 → 超时错误结果，循环继续 DONE；
- timeout_seconds=None → 不超时（长工具正常完成）。
- 既有 agent/parallel/bash 回归绿。
