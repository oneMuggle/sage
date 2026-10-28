# `electron/` 收敛 8a 批：文档注释同步 + main 侧 wire 测试接入（2026-10-28）

> 前序：`mcp-win7-converge-src-types-adr`（#2579）、`…-batch2-chat-chain`（#2580）、
> `…-batch3-settings`（#2581）、`…-batch4-5`（#2584 / #2586）、
> `…-batch6-deps-i18n`（#2588）、`…-batch7-deadcode-arena`（#2595）。
> `src/` 域已于 #2595 收尾，本文开启 `electron/` 域。

## 1. 基线

| 分支 | commit |
|---|---|
| `release/win7` | `39a43558d`（#2595 合并后的头部，其后又有 #2601 / #2604–#2611） |
| `main` | `df23587ee` |

`electron/` 相对 main 的规模：**51 文件 +1523 / −2465**，其中 39 个文件两侧都存在，
7 个 win7 独有、5 个 main 独有。差异不是单向的，**不能整目录取 main**。

## 2. 本批（8a）处置

| 文件 | 处置 | 依据 |
|---|---|---|
| `electron/commandRoutes/index.ts` | 取 main | main 增补 14 行路由表治理注释（#857 事故复盘 + 领域文件规则），无代码差异 |
| `electron/commandRoutes/{memory,orchestration,skills,prompts}.ts` | 取 main | 差异为文件头说明与注释措辞；逐文件比对路由键集，win7 的 `prompts_reorder` 等**一条未丢**（见 §4） |
| `electron/commands.ts` | 取 main | 仅空行归整 |
| `electron/arenaTokenWindow.ts` | 取 main | main 把 `ARENA_TOKEN_PARTITION` 收回模块内（全仓无外部引用） |
| `electron/crashGuard.ts` | 取 main | `emergencyLog` 收回模块内（仅本文件使用） |
| `electron/invoke.ts` | 取 main | `camelToSnakeKeys` 收回模块内 + 一处换行格式 |
| `electron/__tests__/wire/{fetchStub.ts,harness.ts,office.wire.test.tsx,promptReorder.wire.test.tsx}` | 新增（取 main） | main 侧新增的「真桥接」集成测试：用替身 fetch 走完 `invoke → route → body 组装 → 响应映射` 全链 |

### 未纳入本批（含原因）

| 文件 | 原因 |
|---|---|
| `electron/__tests__/wire/projectType.wire.test.tsx` | 断言 `detect-type` 返回对象**深度相等**（3 键）；win7 因 #2601「AI 项目治理」在同一响应上多出 2 个字段，实测 `AssertionError: expected {…(2)} to deeply equal {detectedType:'coding', …(4)}`。契约裁决放在 8b 与 `commandRoutes/projects.ts` 一起做 |

## 3. 8b 待办：win7 独有能力必须先保住

`electron/` 有六块 win7 侧新增、main 侧完全没有的能力，任何「取 main」都必须回填，
否则等于删功能：

| 能力 | 证据（win7 侧引用点） | 规模 |
|---|---|---|
| 技能变更通知中继 | `electron/relay.ts::relaySkillNotifications`、`main.ts`、`src/widgets/chat/ChatInput.tsx`（`skills:notify`）、`electron/__tests__/relay.skillNotifications.test.ts` | main 侧 grep 全为 0（main 在 #2607 之前没有通知链） |
| AI 项目治理路由 | `commandRoutes/projects.ts::projects_{sub_types,profile,analyze,generate_rules}`、`src/shared/api/projectApi.ts`、`ipc-manifest.json` | main 已删 27 行 |
| Win7 进程树强杀 | `electron/orphanBackendKiller.ts::forceKillProcessTree`（`taskkill /F /T`，规避 Win7 上 `TerminateProcess` 的 exit 事件不可靠）、`main.ts` | main 已删 25 行 |
| 启动诊断子系统 | `electron/backendDiagnostics.ts`（342 行）→ `main.ts` 的 `recordLastPlan` / `recordBackendStderr` / `collectAndWriteDiagnostic`（4 处调用） | main 侧 grep 全为 0 |
| 更新下载请求校验 | `electron/update/request.ts`（79 行，部署模式/白名单校验）+ `update/__tests__/request.test.ts`；main 改为直接调 `fetchCompat` | main 已删 79 + 70 行 |
| `runtime-check` 测试钩子 | `electron/runtime-check.ts::_setExecFilePForTesting` + `electron/__tests__/runtime-check.test.ts`（379 行） | win7 568 行 vs main 376 行 |

同时 8b 需要手合并的「两侧都改」大件：`electron/main.ts`（+456/−672）、`backendLauncher.ts`、
`buildManifest.ts`、`diagnosticExport.ts`、`showStartupFailureDialog.ts`、`preload.ts`（媒体/更新通道）、
以及 `commandRoutes/{chat,sessions,settings,office,integrations}.ts` 的路由并集
（win7 多 `agent_chat`、`is_archived` 归档开关、`global_rules_*`；main 把
`permissions_session_auto_approvals` 从 `sessions.ts` 挪进 `settings.ts`）。

## 4. 验证

| 检查 | 结果 |
|---|---|
| 路由键集比对（4 个 route 文件） | win7 键集与新键集**完全相同**，lost = ∅（memory 24 / orchestration 19 / skills 16 / prompts 7） |
| `node_modules/typescript/bin/tsc -p tsconfig.electron.json --noEmit` | 0 error |
| `eslint`（改动 ts/tsx） | 0 error |
| `vitest run electron` | **618 用例 / 200 套件，0 failed，退出码 0** |
| 同批次未纳入 `projectType.wire.test.tsx` | 加入后该套件 1 红（响应多 2 字段），已剔除并记录原因 |

规模：**11 文件，+12 / −26**（`promptReorder.wire` / `office.wire` / `harness` / `fetchStub` 为新增）。

## 5. 后续

1. 8b：按 §3 清单做 `main.ts` 与路由表的手合并，同批清掉 #2595 遗留的
   `electron/main.ts` `diagnostic:browser-check` → `diagnosticExport.runBrowserCheck` 残链。
2. `scripts/`、`.github/`、`backend/tests/` 依次成批。
