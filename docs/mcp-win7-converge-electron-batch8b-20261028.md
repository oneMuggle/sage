# `electron/` 收敛 8b 批：路由并集 + 第 7 批残链清理（2026-10-28）

> 前序：`…-batch7-deadcode-arena`（#2595）、`…-electron-batch8`（#2616，8a 批）。
> 8a 只做了零风险的注释/格式层；本文是 `electron/` 的实质合并批次。

## 1. 基线

| 分支 | commit |
|---|---|
| `release/win7` | `52e4aee08`（含 #2595 / #2616，以及并行落地的 #2601 / #2604–#2611 / #2615 / #2617 / #2620） |
| `main` | `5cd4d5871` |

`electron/` 剩余差异：**34 文件 +1120 / −2135**（8a 时 51 文件 +1523/−2465）。
其中 both-changed 28、win7-only 5、main-only 1。

> **对 8a 文档的更正**：8a §3 列的「六块 win7 独有能力」中，
> **技能通知中继**（`relay.ts::relaySkillNotifications`）与 **AI 项目治理路由**
> （`commandRoutes/projects.ts::projects_*`）已被并行流水线（#2615 / #2601）在两支上对齐，
> 当前两侧 identical。真正只剩 4 块需要保留，见 §3。

## 2. 取 main

| 文件 | 判据 |
|---|---|
| `sageFileProtocol.ts` | main 删 `getRegisteredRoots()`；全仓 grep 仅命中定义处本身，无调用方 |
| `officePaths.ts` | main 删 `legacyExtensionForDocType()`；同上，零引用 |
| `commandRoutes/integrations.ts` | 差异仅文件头注释与一句括号说明 |
| `commandRoutes/office.ts` | 差异仅 `office_word_repair` 的位置与注释扩写，键集相同（38 = 38） |
| `commandRoutes/sessions.ts` | win7 的 `permissions_session_auto_approvals` / `usage_get_session` 已由 main 迁到 `settings.ts`；取 main 不丢键 |
| `commandRoutes/settings.ts` | 上一条的目的地，取 main 即获得两键 |
| `backendLauncher.ts` | 差异为 `DoctorLaunchPlan` 接口位置搬家与注释重写（`--ignore-all-space` 后仍 85 行，逐一看过全是注释/顺序），无行为差异 |
| `diagnosticExport.ts` | main 已删 `runBrowserCheck` + `BrowserCheckItem/Result`，与 #2595 的浏览器自检下线一致（§4） |
| `__tests__/logIpc.test.ts` | main 用 `vi.useFakeTimers()` 冻结时钟，修掉 150 连发跨 1s 限速窗口边界的偶发误判（R115） |
| `__tests__/commands.test.ts` | main 增补 MCP `disabled_tools` 全量替换、`mcp_server_tools`、`mcp_server_authorize`、Attachment RAG 路由断言；对应路由两侧均在 |
| `__tests__/backendLauncher.test.ts` | main 增补 124 行 doctor argv derivation 用例；win7 的 `backendLauncher.ts` 同样有该导出 |
| `__tests__/wire/projectType.wire.test.tsx` | 8a 暂缓的那份，本批实测通过（§5） |

## 3. 保留 win7（main 侧已删/已换的独有能力）

| 文件 | 内容 | main 侧状态 |
|---|---|---|
| `main.ts` | 启动诊断接线（`recordLastPlan` / `recordBackendStderr` / `collectAndWriteDiagnostic` 共 6 处）、`sage-file:register-allowed-paths` IPC、`relaySkillNotifications` 调用 | 全部无对应物 |
| `backendDiagnostics.ts`（342 行） | 启动诊断快照落盘 | 文件不存在 |
| `runtime-check.ts`（568 行 vs 376） | `_setExecFilePForTesting` 测试钩子 + `checkKB2670838`（Win7 KB 补丁检查） | 均已删 |
| `__tests__/runtime-check.test.ts`（379 行） | 上述钩子的用例 | 不存在 |
| `mediaIpc.ts` | 手写 multipart（`randomBytes` 边界 + 文件名 `\r\n\0` 拒绝 + contentType 白名单正则）；main 改用 `formdata-node`，而该包在 win7 仓**从未安装** | 换实现 |
| `__tests__/mediaIpc.offline.test.ts`（44 行） | 上述手写编码路径的用例 | 不存在 |
| `buildManifest.ts` | `PackagingMode`（source / cython / unknown）—— 双构建管线的源码保护开关，被 `backendDiagnostics.ts` 与 `scripts/bundle-python.ps1` 消费 | 已删 |
| `showStartupFailureDialog.ts` | 带「打开诊断目录」的 4 按钮版（诊断路径由启动诊断子系统产出） | 3 按钮版 |
| `orphanBackendKiller.ts` | `forceKillProcessTree()`（`taskkill /F /T`，规避 Win7 上 `TerminateProcess` 的 exit 事件不可达） | 已删 25 行 |
| `update/request.ts`（79 行）+ `update/__tests__/request.test.ts`（70 行） | 部署模式策略校验（offline 拒绝下载、intranet 仅白名单主机）+ `updateDeploymentMode()` | 文件不存在 |
| `updateManager.ts` | 上述策略的两处门控（下载前拒绝、rollback telemetry 仅 online） | 已删 |
| `update/providers/{github,gitlab,gitee,genericHttp}.ts` | 从 `../request` 取 `fetchUpdate` | 改从 `../../fetchCompat` 取 |
| `updateHealthChecker.ts` | Win7 软件合成下主窗口可见性超时 15 s（其余平台 3 s） | 固定 3 s |
| `tests/updateManager.test.ts`、`tests/updateIntegration.test.ts` | 上述更新策略的既有用例 | 已删 41 行 |
| `preload.ts` | `memory.subscribe`（记忆事件 SSE 桥） | 已删 |
| `ipc-manifest.json` | 含 `agent_chat`（生成物，`npm run ipc:manifest` 复跑 285 条命令，零 diff） | 已删该项 |

## 4. 路由并集：唯一实质缺口是 `agent_chat`

逐文件比对两侧路由键（`^\s{2}([a-z_]\w*):\s*\{`）：

| 文件 | win7 | main | 仅 win7 | 仅 main |
|---|---|---|---|---|
| `chat.ts` | 17 | 16 | **`agent_chat`** | — |
| `sessions.ts` | 34 | 32 | `permissions_session_auto_approvals`、`usage_get_session` | — |
| `settings.ts` | 55 | 57 | — | 同上两键 |
| `office.ts` | 38 | 38 | — | — |
| `integrations.ts` | 23 | 23 | — | — |
| `projects.ts` | 52 | 52 | — | — |

处置：`chat.ts` 取 main 后把 `agent_chat` 原样插回 `agent_chat_stream` 之后
（`chatApi.chat()`、`electron/main.ts`、`relay.ts`、`src/features/send-message/*` 都在用它）；
`sessions.ts` / `settings.ts` 全部取 main —— 两键改由 `settings.ts` 承载，**全局键集不减**。

## 5. `projectType.wire.test.tsx`：8a 的暂缓理由已消失

8a 暂缓的原因是该用例断言 `detect-type` 响应**深度相等**（3 键），而 win7 因
「AI 项目治理」多 2 个字段。本批复核时该差异已随 #2601 与 main 对齐
（`commandRoutes/projects.ts` 两侧 identical、`src/shared/api/projectApi.ts` 同形），
直接启用后 **6/6 通过**。

## 6. 第 7 批残链清理（`diagnostic:browser-check`）

#2595 删了渲染侧的 `BrowserEnvironmentSection` / `browserDiagnostics.ts`、preload 的
`browserCheck` 与 `electron-api.d.ts` 类型，但主进程仍留着：

```ts
// electron/main.ts（删除前）
ipcMain.handle('diagnostic:browser-check', async (evt) => {
  if (!isTrustedRenderer(evt.sender)) throw new Error('未授权的窗口请求');
  return runBrowserCheck();
});
```

本批删除该 handler、其 3 行注释、`main.ts` import 列表里的 `runBrowserCheck,`，
并取 main 的 `diagnosticExport.ts`（`runBrowserCheck` 与 `BrowserCheckResult` 一并消失）。
删除后 `git grep browser-check|browserCheck|runBrowserCheck` 在 `electron/`、`src/` **零命中**。

## 7. `main.ts` 的终局：保留 win7 版

`main.ts` 是最大件（+456/−652）。逐项核对两侧符号后判定**保留 win7 版**：

| 核对项 | 结果 |
|---|---|
| `main.ts` 的 import 集合 main-only | **0**（main 没有 win7 缺的依赖） |
| `ipcMain.handle/on` 通道 main-only | **0** |
| 通道 win7-only | `diagnostic:browser-check`（本批删除）、`sage-file:register-allowed-paths`（win7 的 allowed_paths 只读注册，保留） |
| 其余 +456/−652 | 组织方式差异（`app.whenReady()` 链式化、handler 内联、`loadFileWithRetry` 回调化、空行与格式），无功能增量 |

即 main 侧没有 win7 缺少的能力，而 win7 侧有 main 没有的启动诊断，故取 win7 版 + §6 清理即可收敛。

## 8. 验证

| 检查 | 结果 |
|---|---|
| `tsc -p tsconfig.electron.json --noEmit` | 0 error |
| `eslint`（改动文件） | 0 error |
| `vitest run electron` | **636 用例 / 206 套件，0 failed**（8a 时 618 / 200） |
| `npm run ipc:manifest`（重新生成） | 285 commands，**零 diff** |
| 残留 grep | `browser-check` / `browserCheck` / `runBrowserCheck` / `getRegisteredRoots` / `legacyExtensionForDocType` 全部零命中 |
| `node scripts/architecture-check.mjs` | rc 0（70 baselined，slack 313 行 / 6 条） |
| `node scripts/check-font-scale.mjs --max-slack=0` | rc 0（slack 0） |

## 9. `electron/` 收尾结论

本批之后，`electron/` 与 main 的差异只剩 4 块**有意的** win7 独有能力
（启动诊断子系统、Win7 进程树强杀、更新部署策略、runtime-check 补丁检查 / media 手写编码），
它们不是「待收敛」，而是 win7 分支存在的理由。后续按计划进入 `scripts/` 与 `.github/`、`backend/tests/`。
