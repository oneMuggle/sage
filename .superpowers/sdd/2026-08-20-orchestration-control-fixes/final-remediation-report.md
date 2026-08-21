# 编排控制最终 remediation 报告

日期：2026-08-21  
基线：`5cf1cb72`

## 状态

最终 remediation 已完成。子代理 WebFetch 不再执行 DNS 预检后交给 httpx 独立解析，而是采用保守策略：仅接受 URL 中的字面量 IPv4/IPv6 地址，且每个地址必须满足 `ip.is_global`。因此 CGNAT、保留/文档网段、私网、loopback、link-local、multicast、unspecified 和 IPv4-mapped IPv6 非公网地址均被拒绝。子代理请求使用 `trust_env=False`，自动重定向保持关闭；重定向目标也必须重新满足同一字面量公网策略。

默认子代理注册表现在通过 `tempfile.mkdtemp` 为每个子代理分配独立的 `0700` scratch 目录。生命周期结束时在 async runner 的 `finally` 中清理，覆盖正常完成、失败和超时后后台 worker 最终退出的路径。显式传入的 `workspace_root` 不被标记为 owned，也不会由清理逻辑删除。测试覆盖不同根目录、权限、预存在不安全目录/符号链接以及显式 workspace 保留。

两处既有精确 progress 断言已加入 `cancelled: 0`；搜索确认没有其他遗漏的精确 progress fixture。网络异常断言已从 unsafe redirect 测试中拆为独立测试，两个行为均保留。

## 验证

- 后端 focused pytest：**66 passed, 5 warnings**
- 前端指定 Vitest：**4 test files passed, 60 tests passed**
- `npx tsc --noEmit`：**通过**
- touched production files Ruff：**通过**
  - `backend/tools/agent_tool.py`
  - `backend/tools/web_tool.py`
- `git diff --check`：**通过**

5 个后端 warning 是既有 Pydantic v2 class-based config deprecation。前端测试仍输出既有 React `act(...)`、React Router future flag 和调试日志 warning；未作为本轮无关 churn 扩大修复范围。

## 残余风险

取消 API 仍没有认证或 run ownership 校验，不能视为已解决。进程内 registry 和取消控制仍是本地架构边界。真实 Electron IPC、真实模型流以及目标环境 Electron smoke test 本轮未执行。
