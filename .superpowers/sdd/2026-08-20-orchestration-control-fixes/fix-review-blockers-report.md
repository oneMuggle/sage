# 编排控制最终复核报告

日期：2026-08-21
工作树：`fix/orchestration-control-p0`

## 结论

状态：`DONE_WITH_CONCERNS`

本轮已完成最终复核 blocker 的实现、回归测试和技术文档更新。取消链路、stream 注册竞态、取消终态进度、子代理文件系统边界和子代理 WebFetch SSRF 防护均已覆盖。

## 已完成

- run-level cancel 先落库 `cancelled`，再通过活动 stream 同时中断 primary agent 和 dispatcher。
- producer 创建 primary agent 后立即登记 `_ACTIVE_STREAMS`；dispatcher 后绑定，并重放先到的取消标志。
- 前后端 `task_progress` 增加 `cancelled`，取消任务按 terminal 统计；取消-only 任务树隐藏等待和取消控件。
- 仅 subagent readonly registry 对 `ReadFileTool` / `ListDirTool` 启用 workspace enforcement；direct file-tool compatibility 保持不变。
- 仅 subagent WebFetch 启用公共地址和重定向目标校验；普通 WebFetch/WebSearch 行为未改变。
- 技术文档 `docs/technical/42-chat-multi-agent-orchestration.md` §14.4 已记录边界和剩余风险。

## 验证

- Backend focused pytest：`48 passed, 5 warnings`
- Frontend focused Vitest：`28 passed`
- TypeScript：`npx tsc --noEmit` 通过
- Ruff：未能全绿。仓库既有文件存在大量 UP045、PLC0415、SIM103 等规则告警；新增测试还触发既有测试文件中的局部 import/decorator 规则告警。未执行全文件自动修复，避免无关 churn。

## 警告与残余风险

- pytest 仅有既存 Pydantic v2 class-based config deprecation warnings。
- ProgressSection 测试仍有既存 React `act(...)` warning，不影响断言结果。
- cancel API 当前没有认证或 run ownership 校验；本轮只修复运行时控制闭环。
- 桌面端真实 Electron IPC、真实模型流和目标环境 smoke test 未在本地执行。
- 本报告不代表认证、授权或网络层防护已经完整解决。
