# MCP ArenCard 移植 P5：前端控制台（/arena 三页签）

Date: 2026-09-19
Scope: plan §P5 —— `/arena` 路由 + 三页签 + 任务操作（启动/停止/日志/结果/导出）+ token 窗口状态 + 命令面板入口。

## Goal

把 P1-P4 的后端能力（账号池 / 批量注册 job / 抽卡 job / token 窗口）接进
sage 前端：一个 `/arena` 控制台页，三页签可完整操作两类 job。

## What landed

**新文件（9）**

| 文件 | 职责 |
|---|---|
| `src/pages/Arena.tsx` | 三页签控制台（`/arena?tab=accounts\|register\|draw`） |
| `src/widgets/arena/JobConsole.tsx` | 任务监控台：snapshot 轮询 + 事件增量拉取（after_seq 游标）+ 停止 + 导出（注册） |
| `src/widgets/arena/BatchRegisterPanel.tsx` | 批量注册启动器（数量 1-20 / 并发 / 代理 off\|pool） |
| `src/widgets/arena/DrawPanel.tsx` | 抽卡启动器（轮数 / keep_pattern / miss_action archive\|keep\|delete / rename_hit / want_reasoning / 全部或勾选账号）+ 最近 20 条记录表 |
| `src/widgets/arena/TokenWindowCard.tsx` | token 窗口状态卡（health: ready/出票数/出口 IP/UA；state: needed/拒绝计数/代理切换；403 显示启用指引） |
| `src/widgets/arena/__tests__/{JobConsole,BatchRegisterPanel,DrawPanel}.test.tsx` | 组件测试（mock entities/arena） |
| `src/pages/__tests__/Arena.test.tsx` | 页面测试（页签切换 / 403 指引 / 面板挂载） |

**改动（9）**

| 文件 | 改动 |
|---|---|
| `src/entities/arena/api.ts` | +任务/事件/抽卡/token 窗口 API 客户端（含 NDJSON 文本解析 `parseJobEventsNdjson`） |
| `src/widgets/arena/index.ts` | 导出四个新组件 |
| `src/App.tsx` | `+route /arena`；`/arena-accounts` → `Navigate /arena`（旧页面组件与测试保留） |
| `src/pages/index.ts` | `export { default as Arena }` |
| `src/widgets/layout/Sidebar.tsx` | 入口 → `/arena`「Arena」 |
| `src/widgets/command/commandItems.ts` | 命令面板 +「Arena 控制台」（Swords 图标） |
| `electron/main.ts` | `sage:backend-request` 新增 `responseType: 'text'` 分支（NDJSON 等文本端点原样返回；签名内联类型同步） |
| `electron/preload.ts` | `responseType` 联合类型 + `'text'` |
| `src/shared/types/electron-api.d.ts` | 同上（类型面） |

**事件消费架构**：任务事件端点（`/jobs/{id}/events`、`/draw/jobs/{id}/events`）
是**批量回放型** NDJSON（一次返回 after_seq 之后的全量，非长连接流）——因此
JobConsole 用 2s 轮询 + after_seq 游标增量拉取：断连/刷新后从最后 seq 续传，
语义与 plan 的「断流后 after_seq 续传不丢事件」一致；orch 的长流 relay
（`orch-events-*`）不适用于该端点形态。relay 的 `responseType:'text'` 是通用
增益（任何文本端点可经认证通道取回）。

## Deviation from plan

- **i18n 未接入**：arena UI 既有三组件（AccountTable/RegisterAssist/
  ObservationFeed）为中文硬编码，P5 沿用同一风格保持一致；接入
  `shared/lib/i18n` 留待统一迁移（届时一并覆盖旧组件）。
- **lint 基线**：仓库级 `npm run lint` 存量红（30k+ 错误，主要来自
  `.worktrees/` 1197 个文件与 `.tmp-arena-*` 构建产物未被 ignore——均非 P5
  引入）。P5 验收口径 = 全部触点文件 scoped eslint **0 error**。

## Verification

- `vitest run`（全量）：**2663 passed / 1 failed / 3 skipped**；唯一失败
  `electron/__tests__/logIpc.test.ts`（限流时序测试）单跑即绿（0.5s）——
  306s 满载下的既有抖动，与 P5 改动无交集。
- arena 触点测试全绿：arenaTokenWindow 12（含 P3 UA 归一 3 例）、
  JobConsole 3、BatchRegisterPanel 2、DrawPanel 5、Arena 4、
  ArenaAccounts 7（旧页回归）。
- `npm run typecheck` = 0；`npm run typecheck:electron` = 0。
- scoped `eslint`（P5 全部触点文件）= 0。

## Notes & follow-ups

- 抽卡页在真实环境下会到 recaptcha 门（P4 结论：需住宅代理，P6）；
  UI 侧已就绪——任务/记录/token 窗口卡在真代理接入后即可端到端。
- 导出按钮仅注册任务提供（`/registration/jobs/{id}/export` =
  register_results 文本，浏览器端 Blob 另存）；抽卡记录经页面表格消费，
  如需 CSV 导出可后续加。
- token 窗口启停仍是 yaml 配置（`token_window.enabled`），UI 显示状态与
  403 指引；in-app 开关需要后端 config 写入端点（未在 P1-P4 契约内，未加）。
- P3 UA 归一化修复的 dist 产物（`.tmp-arena-p3/dist`）仍是修复前版本，
  下次前端构建自动更新（P4 文档已记）。
