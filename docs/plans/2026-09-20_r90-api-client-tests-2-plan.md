# R90 批次计划 —— API Client 测试覆盖收口（第二批）

日期：2026-09-20 ｜ worktree：`.worktrees/feat-r90-batch`（基于 origin/main 0c2a4de2）

## 背景

r84-r89 已覆盖 sessionApi / projectApi / gatewayApi / permissionApi / orchRunControlClient /
mediaApi 等。扫描 `src/shared/api/` 后仍有 5 个无专属测试的 client：

| 文件 | 行数 | 面积 |
| --- | --- | --- |
| `promptApi.ts` | 107 | 模板 CRUD / reorder / 导入导出信封（conflict=skip/overwrite） |
| `mcpClient.ts` | 146 | MCP 服务器 CRUD（rawBody snake_case 约定）/ 工具清单 / OAuth 授权 / 名称正则 |
| `agentsApi.ts` | 84 | list / toggle / update(diff) / create(透传) |
| `runtimeApi.ts` | 91 | probe / diagnose / exec（snake_case→camelCase 桥接映射） |
| `messageApi.ts` | 28 | delete（ID 校验 + ApiException） |

apiClients.test.ts 只覆盖了上述各家的零星错误路径，行为面（payload 形状、字段映射、
默认值、信封包装）无断言。

## 批次内容

新增 5 个测试文件（`src/shared/api/__tests__/`）：

1. `promptApi.test.ts`（11 用例）——list 解包/兜底空数组、create 默认 description、
   update 部分补丁、remove/reorder 通道、export 信封原样、import 默认 conflict=skip
   与显式 overwrite 的 payload 包装。
2. `mcpClient.test.ts`（11 用例）——status/listServers 解包、addServer rawBody
   snake_case 默认值（env={}/enabled=true/timeout_seconds=30）与 url/headers 条件包含、
   updateServer camel→snake 映射、serverTools/authorizeServer/deleteServer 通道、
   `MCP_NAME_REGEX` 边界（1/64 合法、65/大写/空串/中文拒绝）。
3. `agentsApi.test.ts`（5 用例）——四方法通道与 payload、toggle 错误经 withRetry
   重试 4 次后包装（fake timers 推进 8s）。
4. `runtimeApi.test.ts`（6 用例）——probe 默认值填充、snake_case 请求字段→camelCase
   桥接键映射（include_tools→includeTools、project_root→projectRoot、
   runtime_path→runtimePath、env_overrides→envOverrides）、exec 可选键置 null、
   handleApiError 包装。
5. `messageApi.test.ts`（5 用例）——合法 id 通道、空 id / 非 string id 抛
   VALIDATION_ERROR 且不触 invoke、details 带 messageId、withRetry 重试后包装
   （fake timers）。

## 验证矩阵

- `npx vitest run src/shared/api/__tests__/{promptApi,mcpClient,agentsApi,runtimeApi,messageApi}.test.ts`
- `npx tsc --noEmit`（如 CI 前端步骤同款）

## 不做

- 不改任何源码（纯测试批次）。
- 不动 win7 分支（测试属增强，按 31-win7-lts.md §2 不回移）。

## 风险

- agentsApi/messageApi 错误路径使用 fake timers：withRetry 的 setTimeout 被 vitest
  拦截，`advanceTimersByTimeAsync(8000)` 覆盖 1+2+4s 退避，预期 4 次调用。
- `it.each` 空格 id 用例已修正：`'   '` 为 truthy 会通过现有校验（记录为现状行为，
  不在本批改源码）。
