# `src/` 收敛第 4–5 批 + 剩余盘点（2026-10-27）

> 前序：types 裁决（`mcp-win7-converge-src-types-adr-20261027.md`，#2579）、
> chat 域（`mcp-win7-converge-src-batch2-chat-chain-20261027.md`，#2580）、
> settings 域（`mcp-win7-converge-src-batch3-settings-20261027.md`，#2581）。
> 本文覆盖第 4 批（shared 层 / providers / 全局样式，PR #2584）与第 5 批（agents / project-type / 文档区测试，PR #2586），
> 并把仍留在 `release/win7` 上的差异逐项列出，作为后续批次的输入。

## 1. 第 4 批：shared 层（14 文件，+498 / −53）

| 区域 | 处理 | 备注 |
|---|---|---|
| `shared/ui/{index,ErrorState,LoadingState,RetryButton}` | 取 main | main 去掉 `export type { *Props }` 转发，类型改由组件文件导出；`audit*BarrelGovernance` 两版一致 |
| `shared/api/types/templateAndTaskTypes.ts` | 取 main | 与第 1 批 `officeDocTypes` 裁决后的符号集对齐 |
| `shared/api/__tests__/{apiClients,promptApi}` | 新增（main 独有） | — |
| `shared/api/__tests__/orchRunClient.test.ts` | 取 main | — |
| `app/providers/{AppProviders,index}` | 取 main | — |
| `entities/endpoint/providerRegistry.ts` | 取 main | — |
| `entities/theme/__tests__/presets.test.ts` | 新增 | — |
| `src/index.css` | 取 main | — |

### 4.1 `electron-api.d.ts` 的三方合并

两侧互补，整份取任一方向都会丢东西：

| 方向 | 内容 |
|---|---|
| main 独有 | `remoteMcp?: RemoteMcpElectronApiBridge`（Workspace MCP Server，可选桥） |
| win7 独有 | `memory.subscribe`（记忆事件 SSE 桥）、`diagnostic.browserCheck`（浏览器自检，`BrowserEnvironmentSection` 依赖） |

整份取 main 会让 `pages/Memory.tsx` 与 `shared/api/browserDiagnostics.ts` 各 2 处 `TS2339`。
最终以 main 为基底回填 win7 的两段声明，540 行，`tsc` 0 error。

## 2. 第 5 批：agents / project-type / 文档区测试（8 文件，+1567 / −1184）

取 main：`pages/Agents.tsx`、`features/project-type/{ProjectArchetypeStudio,TypeDetectionPreview}.tsx`、
`widgets/agents/__tests__/EditAgentForm.tools.test.ts`、`widgets/memory/__tests__/MemoryBrowser.test.tsx`、
`widgets/wiki/__tests__/WikiChat.sources.test.tsx`；
新增 main 独有：`EditAgentForm.staleEntries.test.tsx`、`Layout.panelCoordination.test.tsx`。

### 2.1 一次失败的尝试（记录以免重犯）

试取 main 的 `pages/Arena.tsx` + `pages/ArenaAccounts.tsx` + `widgets/arena/AccountTable.tsx` 后，
`pages/__tests__/ArenaAccounts.test.tsx` 两个用例红：

- `Unable to find an element by: [data-testid="account-row-user1@example.com"]`（页面渲染为空）
- `Found multiple elements by: [data-testid="account-table-empty"]`

该测试文件两侧**内容完全相同**（`git diff` 空），说明是 main 版表格与 win7 侧 mock/store 组合不兼容，
不是测试文案问题。已回退这三个文件，留给 arena 整域批次一起裁。

## 3. 剩余盘点（本批之后 `src/` 的 divergence）

### 3.1 需要手合并（win7 有独有能力）

| 文件 | win7 独有内容 | 量级 |
|---|---|---|
| `pages/Memory.tsx` | Memory Tabs/Card 结构重写 | win7-only 350 行 |
| `widgets/wiki/MarkdownPreview.tsx` | KaTeX 插件（`remark-math` + `rehype-katex`） | 6 行 import/配置 |
| `widgets/command/CommandPalette.test.tsx` | `buildCommandPaletteAuditSnapshot` 等 audit 断言 | 132 行 |
| `features/{diagnostic,journal,office}/index.ts` | 额外类型导出 + `BrowserEnvironmentSection`（main 已删该组件） | 1–2 行/文件 |
| `features/chat/__tests__/BtwOverlay.latex.test.tsx` | win7 的 KaTeX 断言（第 2 批保留） | — |

### 3.2 需要新依赖才能收敛

| 文件 | 依赖 | 说明 |
|---|---|---|
| `widgets/chat/ShikiCodeBlock.tsx` | `@shikijs/langs`、`@shikijs/themes`（main 用 `shiki/core` + 逐语言动态导入） | 随 `package.json` 依赖批次一起做 |

### 3.3 结构性删除（main 已删、win7 仍在用）

| 文件 | 状态 |
|---|---|
| `shared/ui/DropdownMenu/index.ts` | main 删除；win7 的 `DropdownMenu.tsx` 与 `__tests__/DropdownMenu.p149.test.ts` 仍引用 |
| `shared/ui/Select/index.ts` | main 删除；win7 的 `widgets/welcome/{ModelPicker,ProjectPicker,WorktreePicker}.tsx` 引用 |
| `shared/ui/Switch/index.ts` | main 删除；win7 内无引用（可直接删） |
| `widgets/evolution/index.ts` | main 删除；win7 内无引用（可直接删） |

> 这批需要先确认 main 侧对应组件的导入方式（是否改为直接 `./Select` 路径），再成对改动引用点，故单列。

### 3.4 行尾归一化

`WorkspaceBranchPicker.tsx` 等 win7 blob 为 CRLF，与 main 内容 token 级相同。全仓 CRLF→LF 归一化应作为独立 PR（`.gitattributes` + 一次性重写），不混入功能批次。

### 3.5 i18n 语言包

6 个 locale 文件（`zh|en` × `chatAndSider|settingsAndModels|workspaceAndTools`）差异是**键集并集**问题：

| 文件 | main 独有键 | win7 独有键 |
|---|---|---|
| `zh/chatAndSider` | 4（`chat.rag_citation*`） | 23（`settings.network.browser_env.*` 等） |
| `en/chatAndSider` | 4 | 19 |
| `zh/settingsAndModels` | 12（`updates.channel*` 等） | 5（`settings.density.label`、`office.preview.*`） |
| `en/settingsAndModels` | 8 | 4 |
| `zh/workspaceAndTools` | 5 | 0 |
| `en/workspaceAndTools` | 4 | 0 |

正确处理是**并集合并**（以 main 为基底 + 回填 win7 独有键），不能用整份覆盖，否则 win7 独有的
`BrowserEnvironmentSection` / 密度设置 / office 预览文案会缺键。这一批可与 ShikiCodeBlock + `package.json` 合并成"依赖与 i18n 批"。

## 4. 第 4–5 批闸门

| 闸门 | 第 4 批 | 第 5 批 |
|---|---|---|
| `tsc -p tsconfig.json --noEmit` | 0 error | 0 error |
| `node scripts/architecture-check.mjs` | rc 0 | rc 0 |
| `node scripts/check-font-scale.mjs --max-slack=0` | rc 0 | 未触发 |
| `eslint`（改动 ts/tsx） | 0 error | 0 error |
| vitest | 260 用例 0 失败 | 350 用例 0 失败 |

## 5. 累计进度（本次会话）

| PR | 范围 | 规模 | 状态 |
|---|---|---|---|
| #2579 | types 布局裁决 + office 契约对齐 | 5 文件 +173/−47 | merged |
| #2580 | chat 域 / 投递通道整链 | 47 文件 +2685/−707 | merged |
| #2581 | settings 域 + 端点/权限客户端 | 36 文件 +1698/−854 | merged |
| #2584 | shared 层 / providers / 全局样式 | 14 文件 +498/−53 | merged |
| #2586 | agents / project-type / 文档区测试 | 8 文件 +1567/−1184 | 本 PR |

至此 `src/` 的 `both` 与大部分 `nobase-both` 已收敛；剩余项见 §3，按 §3.5 的"依赖与 i18n 批"、§3.1 的"手合并批"、§3.3 的"结构性删除批"分三次推进，之后再进入 electron 域。
