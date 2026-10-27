# `src/` 收敛第 3 批：settings 域（2026-10-27）

> 前两批：`docs/mcp-win7-converge-src-types-adr-20261027.md`（#2579）、
> `docs/mcp-win7-converge-src-batch2-chat-chain-20261027.md`（#2580）。
> 本文记录 settings 域（页面 + 注册表 + 端点/权限客户端）的收敛依据与闸门结果。

## 1. 基线

| 分支 | commit |
|---|---|
| `release/win7` | `70a8015b`（#2580 合并后） |
| `main` | `6885594` |
| merge-base | `476904b4` |

## 2. 判定：settings 域两侧差异的性质

settings 域在本基线上共 35 个文件有差异（`both` 13 + `nobase-both` 19 + `mainly-add` 3），
逐文件核对 win7-only 行（`git diff -w win7 main` 的删除侧）后结论分三类：

| 类型 | 例子 | 处理 |
|---|---|---|
| win7 侧是 main 的旧实现 | `GeneralTab.tsx`（main +126/−2）、`MemoryKnowledgeTab.tsx`（+211/−8） | 取 main |
| main 主动重构 | `settingsSearchIndex.ts`（+27/−28，索引化）、`settingsPresentation.ts`、`OrchestrationTab.tsx`（+27/−44） | 取 main |
| main 修正文案/语义 | `errorMapping.ts`（「设置 → 编排」）、`PermissionRulesManager.tsx`（shadowed 判定） | 取 main |

win7-only 行中无平台分支、无 win7 独有能力（延续第 2 批的判据）。

## 3. 变更清单（35 文件，+1588 / −854）

### 3.1 `pages/settings`（14 个实现 + 9 个测试）

`GeneralTab`、`EndpointsTab`、`NetworkTab`、`BasicTab`、`OrchestrationTab`、`MemoryKnowledgeTab`、
`PermissionRulesManager`、`ToolsConnectionsTab`、`FontSettingsSection`、`NetworkCredentialsSection`、
`ContextTurnLimitSelect`、`components`、`settingsPresentation`、`settingsSearchIndex` 全部取 main。

新增 main 独有的 3 个测试：`MemoryKnowledgeTab.clearAll.test.tsx`（204 行）、
`PermissionRulesManager.shadowed.test.tsx`（132 行）、`Settings.anchor.test.tsx`（183 行）——
这三个测试覆盖的正是 main 侧新增的"清空全部记忆"、"规则被遮蔽"标注、"设置锚点深链"能力。

### 3.2 `entities/setting`

`types.ts`（+10/−18）与 `settingsRegistry.ts`（+6/−40）取 main：main 把设置项元数据收进注册表，
win7 侧仍是分散声明。

### 3.3 客户端

| 文件 | 差异 | 说明 |
|---|---|---|
| `features/manage-endpoints/api.ts` | +12/−79 | main 收敛了端点管理 API 层 |
| `shared/api/mcpClient.ts` | +9/−10 | 对齐 main |
| `shared/api/permissionApi.ts` | +1/−5 | 对齐 main |
| `shared/lib/errorMapping.ts` | +3/−3 | 「设置 → 编排」文案修正（第 1 批遗留待办） |

### 3.4 `widgets/settings`

`HookHistoryPanel.tsx`、`ProjectHooksPanel.tsx` 取 main（内容与 main 一致，仅空白/换行差异）。

## 4. 闸门：两个棘轮基线

本批触发了两条既有棘轮闸门，处理方式与 main 一致：

### 4.1 `architecture-baseline.json`

无本批新增条目（第 2 批已把 `useChat.ts` 998 / `ChatInput.tsx` 853 抬高），本批 arch 检查 rc 0。

### 4.2 `scripts/font-scale-baseline.json`（U3）

main 版 `EndpointsTab.tsx` 含 **6 处** `text-[Npx]` 硬编码：

| 行 | 内容 |
|---|---|
| 238 | `<span className="text-[11px] text-muted">{discoveredModels.length} 个模型</span>` |
| 326 | `<label className="text-[11px] text-muted/80 block mb-1">` |
| 334 | `className="... text-[11px] font-mono bg-surface text-text"` |
| 336 | `<p className="text-[10px] text-muted/70 mt-0.5">` |
| 450 | `<div className="flex items-center gap-3 text-[10px] text-muted/70">` |
| 482 | `<div className={clsx('mt-2 px-2 py-1.5 rounded-radius-sm text-[11px]', config.bg)}>` |

`fontScaleGate.test.ts` 用 `--max-slack=0` 跑 `scripts/check-font-scale.mjs`；win7 的
`font-scale-baseline.json` 原本是空 `files`，因此这 6 处会被判为回归。
main 侧已把它们记入基线（`files` 只有这一条：`src/pages/settings/EndpointsTab.tsx: 6`），
故本批**取 main 的 baseline 文件**，保持与 main 完全一致的棘轮记录：

```
Font-scale check passed (6 baselined occurrences across 1 files, slack=0)
```

> 备注：这批 px 属 main 侧遗留债，本批只做对齐、不做修复（修复会与 main 产生无谓冲突）；
> 待后续"UI 密度 token 化"专项统一处理，届时两侧同时下降 baseline。

## 5. 闸门结果

| 闸门 | 结果 |
|---|---|
| `tsc -p tsconfig.json --noEmit` | 0 error（一次通过，无需补 i18n 键） |
| `tsc -p tsconfig.electron.json --noEmit` | 0 error |
| `node scripts/architecture-check.mjs` | rc 0（67 baselined，slack 393 行） |
| `node scripts/check-font-scale.mjs --max-slack=0` | rc 0（6 baselined，slack 0） |
| `eslint`（34 个改动 ts/tsx） | 0 error（2 warning 为 `react-refresh`，与 main 同源） |
| vitest `pages/settings/__tests__` + `widgets/settings` + `shared/api` 2 个 + `shared/lib/__tests__` | 664 passed / 0 failed |
| vitest `src/__tests__` + `src/app` + `features/manage-endpoints` | 102 passed / 0 failed |

## 6. 剩余（后续批次）

| 域 | 文件数（both/nobase-both） | 备注 |
|---|---|---|
| arena / memory / wiki / todo | 约 15 | `pages/Arena*`、`widgets/memory/*`、`widgets/wiki/*` |
| 其余 `both` 尾项 | 约 12 | `index.css`、`app/providers`、`shared/ui/*` barrel、`diagnostic`、`journal`、`office/index` |
| 依赖面 | `package.json` + lockfile | `ShikiCodeBlock`（`@shikijs/*`）随此批 |
| 行尾归一化 | `WorkspaceBranchPicker.tsx` 等 | CRLF blob → LF |
