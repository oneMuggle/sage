# `src/` 收敛第 7 批：死代码清理 + 浏览器自检下线（2026-10-27）

> 前序：`mcp-win7-converge-src-types-adr`（#2579）、`…-batch2-chat-chain`（#2580）、
> `…-batch3-settings`（#2581）、`…-batch4-5`（#2584 / #2586）、
> `…-batch6-deps-i18n`（#2588）。
> 本文覆盖第 4–5 批盘点里剩余的全部 `src/` 条目，是 `src/` 域的收尾批次。

## 1. 基线

| 分支 | commit |
|---|---|
| `release/win7` | `5191290fe`（含 #2588 / #2587 / #2591 / #2592） |
| `main` | `4219d862` |

## 2. 逐项裁决

| 文件 / 目录 | 处置 | 依据 |
|---|---|---|
| `pages/Memory.tsx` | 取 main | 列表容器改由 `MemoryBrowser` 承载，win7 的 Tabs/Card 结构（+28/−350）整体退场 |
| `widgets/memory/{MemoryCard,MemoryTabs}.tsx` | 删除 | 上一条的配套件，取 main 后无消费方 |
| `widgets/memory/__tests__/{MemoryCard,MemorySSE}.spec.tsx` | 删除 | 随被测组件一起退场（190 行） |
| `widgets/command/CommandPalette.test.tsx` | 取 main | main 侧 439 行；`buildCommandPaletteAuditSnapshot` 仅存于 win7 测试内，组件两侧 696 行同内容 |
| `widgets/wiki/MarkdownPreview.tsx` | 取 main | win7 只多 `remarkMath` 插件一行与注释，KaTeX 能力由 `BtwOverlay` 侧承载，不受影响 |
| `features/{diagnostic,journal,office}/index.ts` | 取 main | 所删导出均只被 barrel 自身引用（见 §3） |
| `shared/ui/{DropdownMenu,Select,Switch}/index.ts` | 删除 | 全仓无任何 `import … from 'shared/ui/<X>'`；组件自身 `.tsx` 路径保持可用 |
| `widgets/evolution/index.ts` | 删除 | 同上，`git grep` 零命中 |
| `features/diagnostic/BrowserEnvironmentSection.tsx` | 删除 | 见 §4 |
| `shared/api/browserDiagnostics.ts` | 删除 | 见 §4 |
| `electron/preload.ts` + `shared/types/electron-api.d.ts` | main 基底 + 回填 | 保留 win7 的 `memory.subscribe`（SSE 桥），其余成员全部跟随 main |
| `pages/{Arena,ArenaAccounts}.tsx`、`widgets/arena/AccountTable.tsx` | 核对无差异 | `window.confirm` → `TwoStepDelete` 已由 #2587 在 win7 侧落地，本批复核后走空 |
| `shared/lib/hooks/usePluginNames.ts` | 核对无差异 | 同上，已随 #2587 进入 `release/win7` |
| `shared/lib/permissionInsights.ts`、`widgets/chat/{Message,PermissionModeSwitch}.tsx` | 取 main | 插件归属（`findPluginToolOwner`）能力整链，含 `Message.pluginOwner` / `PermissionModeSwitch` 测试 |

## 3. barrel 导出裁剪的影响面

`features/{diagnostic,journal,office}/index.ts` 取 main 后消失的导出，逐个核对消费方：

| 导出 | win7 侧引用点 |
|---|---|
| `PreviewResponse`（type） | 无（仅 barrel 自身 `export type`） |
| `BrowserEnvironmentSection` | `pages/Diagnostic` 未渲染，仅 `electron-api.d.ts` 注释提及 |
| `UseJournalTemplatesReturn` / `JournalContentDraft`（type） | 无 |
| `OfficeGenerateFormProps` / `OfficeCapabilityBarProps`（type） | 无 |

结论：本次裁剪不改变任何运行期可达路径，`Office.workspace.test.tsx` 的
`vi.mock('../../features/office')` 与三个 `*.p162` barrel 自检用例均保持通过。

## 4. 浏览器环境自检：整域下线

win7 独有的「浏览器环境自检」在 main 侧从未存在，且**全仓无渲染入口**：

| 组成 | 行数 | 处置 |
|---|---|---|
| `features/diagnostic/BrowserEnvironmentSection.tsx` | 156 | 删除 |
| `shared/api/browserDiagnostics.ts` | 37 | 删除 |
| `electron/preload.ts` 的 `diagnostic.browserCheck` | 13 | 删除 |
| `shared/types/electron-api.d.ts` 的 `browserCheck` 类型 | 12 | 删除 |
| i18n `settings.network.browser_env.*` | 11 键 × 2 语言 | 删除 |

证据链：`pages/Diagnostic` 未挂载该组件；`git grep browserCheck|browserDiagnostics|
BrowserEnvironmentSection` 在删除后零命中；`browser_env` 在 6 个 locale 文件零残留。
该判定已在动笔前经用户确认（保留未完成特性 vs **直接删除**），历史可从本 PR 反向恢复。

## 5. i18n

| 指标 | 结果 |
|---|---|
| 键数 | zh `1210` = en `1210`（对称，零重复） |
| 相对 main（`1209`） | 严格超集，仅多 `settings.density.label` |
| `browser_env` 残留 | 0 |
| `t('…')` 静态扫描 | 616 文件 / 978 键，缺 40 —— 与收敛前 win7/main 完全一致的既有缺口 |

## 6. 验证

| 检查 | 结果 |
|---|---|
| `tsc -p tsconfig.json --noEmit` | 0 error |
| `tsc -p tsconfig.electron.json --noEmit` | 0 error |
| vitest `shared/ui/{Select,DropdownMenu,Switch}` + `usePluginNames` | 23 passed / 0 failed |
| vitest `widgets/memory` + `pages/__tests__/Memory.export.test.tsx` | 45 passed / 0 failed |
| vitest `Arena*` + `widgets/arena` | 45 passed / 0 failed |
| vitest `widgets/command` + plugin 归属 3 件 | 48 passed / 0 failed |
| vitest `features/{diagnostic,journal,office}` | 259 passed / 0 failed |
| `node scripts/architecture-check.mjs` | rc 0（67 baselined，slack 393 行 / 7 条） |
| `node scripts/check-font-scale.mjs --max-slack=0` | rc 0（6 baselined，slack 0） |
| `eslint`（改动 ts/tsx） | 0 error（`Message.tsx` 2 条 `react-refresh` warning 来自 main，非本批引入） |

规模：**26 文件，+324 / −1190**。

## 7. `src/` 域收尾状态

| 项 | 状态 |
|---|---|
| types 布局裁决 | #2579 已并 |
| chat / settings / shared / agents / 文档区 | #2580 / #2581 / #2584 / #2586 已并 |
| 依赖声明 + i18n 并集 + ShikiCodeBlock | #2588 已并 |
| 死代码、Memory、CommandPalette、浏览器自检 | 本批 |

`src/` 之外仍待收敛（后续批次）：`electron/`、`scripts/` 与 `.github/`、`backend/tests/`。
